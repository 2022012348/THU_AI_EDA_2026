"""固定流水线的子 Agent 基类与运行上下文。

交接记录只保存小型消息与 artifact 引用；RTL、Spec、Plan 和测试报告均落盘一次，
由接收方按引用读取，避免在 handoff 中复制大文本。
"""

from __future__ import annotations

import json
import hashlib
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ai_eda.model.client import RTL_SYSTEM_PROMPT, EmptyModelResponseError, ModelClient
from ai_eda.token_metrics import estimate_output_tokens, output_tokens as reported_output_tokens


class ModelCallBudgetExceeded(ValueError):
    """Visible model-call limit, distinct from an invalid model repair."""


class RunContext:
    def __init__(
        self,
        *,
        run_dir: Path,
        options: dict[str, Any],
        begin_event: Callable[..., dict[str, Any]],
        finish_event: Callable[..., None],
        persist: Callable[..., None],
        emit: Callable[[dict[str, Any]], None],
        check_cancel: Callable[[], None],
        request_input: Callable[[dict[str, Any]], str] | None,
        max_calls: int = 100,
    ) -> None:
        self.run_dir = run_dir
        self.options = options
        self.begin_event = begin_event
        self.finish_event = finish_event
        self.persist = persist
        self.emit = emit
        self.check_cancel = check_cancel
        self.request_input = request_input
        self.max_calls = int(max_calls)
        self.model_calls = 0
        self.handoffs_dir = run_dir / "handoffs"
        self.handoffs_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir = run_dir / "artifacts"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

    def make_client(self, overrides: dict[str, Any] | None = None) -> ModelClient:
        model_keys = ("temperature", "max_tokens", "thinking", "reasoning_effort")
        options = {key: self.options[key] for key in model_keys if key in self.options}
        if overrides:
            options.update({key: value for key, value in overrides.items() if key in model_keys})
        return ModelClient(**options)

    def _record_model_usage(self, event, messages, usage, output, status):
        record = {'call_index': self.model_calls, 'status': status, 'usage': usage,
                  'estimated_prompt_tokens': estimate_output_tokens(''.join(m.get('content', '') for m in messages)),
                  'output_tokens': reported_output_tokens(usage, output),
                  'usage_source': 'provider' if isinstance(usage, dict) else 'estimate'}
        event.setdefault('model_call_usage', []).append(record)
        # Record every format recovery or empty-response retry, not only the
        # last successful call in a step. Estimates are explicitly labelled.
        with (self.run_dir / 'model_usage.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(dict(record, node_id=event.get('node_id'), step=event.get('step')), ensure_ascii=False) + '\n')

    def call_model(
        self,
        event: dict[str, Any],
        prompt: str,
        system_prompt: str,
        *,
        model_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """单轮模型调用：内部包装成 system + user 的消息历史。"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        return self.call_model_messages(
            event, messages, artifact_prompt=prompt, model_options=model_options
        )

    def call_model_messages(
        self,
        event: dict[str, Any],
        messages: list[dict[str, str]],
        *,
        artifact_prompt: str | None = None,
        model_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """使用已有消息历史做模型调用，支持 Modifier 等子 Agent 的多轮上下文。"""
        event["conversation_messages"] = len(messages)
        client = self.make_client(model_options)
        last_emit = 0.0
        last_persist = 0.0
        for attempt in range(ModelClient.EMPTY_CONTENT_RETRIES + 1):
            self.check_cancel()
            if self.max_calls > 0 and self.model_calls >= self.max_calls:
                raise ModelCallBudgetExceeded(
                    f"Agent 模型调用次数已达到上限（{self.max_calls} 次），"
                    "请提高调用上限或缩小任务规模。"
                )
            self.model_calls += 1
            event["call_index"] = self.model_calls
            answer_parts: list[str] = []
            reasoning_parts: list[str] = []
            usage: dict[str, Any] | None = None
            finish_reason: str | None = None
            got_done = False
            event["streaming"] = True
            event["reasoning"] = ""
            event["response"] = ""
            event["output_tokens"] = 0
            try:
                for chunk in client.stream_chat_detail(messages):
                    self.check_cancel()
                    kind = chunk.get("type")
                    if kind == "reasoning":
                        reasoning_parts.append(str(chunk.get("text") or ""))
                    elif kind == "answer":
                        answer_parts.append(str(chunk.get("text") or ""))
                    elif kind == "done":
                        got_done = True
                        answer_parts = [str(chunk.get("answer") or "")]
                        reasoning_parts = [str(chunk.get("reasoning") or "")]
                        usage = chunk.get("usage")
                        finish_reason = chunk.get("finish_reason")
                    event["reasoning"] = "".join(reasoning_parts)
                    event["response"] = "".join(answer_parts)
                    event["output_tokens"] = estimate_output_tokens(
                        event["response"] + (event["reasoning"] or "")
                    )
                    now = time.monotonic()
                    if now - last_emit >= 0.12:
                        self.emit(json.loads(json.dumps(event, ensure_ascii=False)))
                        last_emit = now
                    if now - last_persist >= 1.0:
                        self.persist()
                        last_persist = now
            except EmptyModelResponseError as error:
                self._record_model_usage(event, messages, error.usage,
                    ''.join(answer_parts + reasoning_parts), 'empty_response')
                if error.finish_reason == "length" or attempt >= ModelClient.EMPTY_CONTENT_RETRIES:
                    raise
                event.setdefault("empty_response_retries", []).append({
                    "call_index": self.model_calls, "error": str(error),
                })
                # Some gateways stop after a long reasoning-only response. A
                # retry with identical settings can repeat the same failure;
                # request a direct answer while keeping the messages intact.
                if getattr(client, "thinking", False) and reasoning_parts:
                    retry_options = dict(model_options or {})
                    retry_options["thinking"] = False
                    client = self.make_client(retry_options)
                    event["empty_response_retries"][-1]["retry_thinking"] = False
                self.persist()
                continue
            if not got_done:
                raise RuntimeError("模型流式响应没有正常结束。")
            self._record_model_usage(event, messages, usage, ''.join(answer_parts + reasoning_parts),
                                     'truncated' if finish_reason == 'length' else 'completed')
            break
        self.check_cancel()
        answer = "".join(answer_parts)
        reasoning = "".join(reasoning_parts) or None
        result = {
            "answer": answer,
            "reasoning": reasoning,
            "usage": usage,
            "finish_reason": finish_reason,
        }
        artifact_dir = self.run_dir / f"step-{event['step']:02d}-{event['node_id']}"
        artifact_dir.mkdir(exist_ok=True)
        prompt_for_artifact = artifact_prompt or str(messages[-1].get("content") or "")
        # Keep the traditional latest files for existing UI readers, plus one
        # immutable record per completed model call within this step. Modifier
        # may make several format-recovery calls in a single event.
        call_dir = artifact_dir / f"call-{self.model_calls:04d}"
        call_dir.mkdir(exist_ok=False)
        for directory in (artifact_dir, call_dir):
            (directory / "prompt.md").write_text(prompt_for_artifact, encoding="utf-8")
            (directory / "conversation.json").write_text(
                json.dumps(messages, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            (directory / "raw_response.txt").write_text(answer, encoding="utf-8")
            if reasoning:
                (directory / "reasoning.txt").write_text(reasoning, encoding="utf-8")
            elif directory == artifact_dir and (directory / "reasoning.txt").exists():
                (directory / "reasoning.txt").unlink()
        event["response"] = answer
        event["raw_response"] = answer
        event["reasoning"] = reasoning
        event["usage"] = usage
        event["output_tokens"] = reported_output_tokens(usage, answer + (reasoning or ""))
        event["streaming"] = False
        event["finish_reason"] = finish_reason
        if finish_reason == "length":
            raise RuntimeError(
                "模型输出被截断（finish_reason=length）；已保存部分回答，"
                "不能作为完整 RTL 或 JSON 使用。请提高 max_tokens 或缩短上下文。"
            )
        return result

    def mark_waiting(self, event: dict[str, Any], request: dict[str, Any]) -> None:
        event["status"] = "waiting_input"
        event["input_request"] = request
        self.persist()
        self.emit(json.loads(json.dumps(event, ensure_ascii=False)))

    def artifact_ref(self, path: Path) -> str:
        """把运行目录内的文件转换为可在 handoff 中传递的相对引用。"""
        resolved = path.resolve()
        root = self.run_dir.resolve()
        if root not in resolved.parents:
            raise ValueError("artifact 必须位于当前运行目录")
        return str(resolved.relative_to(root))

    def _resolve_ref(self, reference: str, *, directory: Path | None = None) -> Path:
        if not isinstance(reference, str) or not reference.strip():
            raise ValueError("artifact 引用不能为空")
        root = (directory or self.run_dir).resolve()
        path = (root / reference).resolve()
        if root not in path.parents:
            raise ValueError("artifact 引用越出运行目录")
        return path

    def write_text_artifact(self, name: str, content: str) -> str:
        path = self._resolve_ref(name, directory=self.artifacts_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return self.artifact_ref(path)

    def write_json_artifact(self, name: str, payload: Any) -> str:
        return self.write_text_artifact(name, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    def snapshot_rtl_manifest(self, files: dict[str, str], snapshot_id: str) -> dict[str, Any]:
        """Freeze one complete RTL version and return a compatible manifest.

        Project files remain editable during repair. Handoffs instead point to
        files here so an earlier Tester input is not silently changed later.
        """
        if not re.fullmatch(r"[A-Za-z0-9_-]+", snapshot_id or ""):
            raise ValueError("RTL 快照名称无效")
        if not isinstance(files, dict) or not files:
            raise ValueError("RTL 快照必须包含文件")
        normalized: set[str] = set()
        for relative, content in files.items():
            if not isinstance(relative, str) or not isinstance(content, str):
                raise ValueError("RTL 快照文件格式无效")
            path = Path(relative)
            if path.is_absolute() or "\\" in relative or any(p in {".", ".."} for p in relative.split("/")):
                raise ValueError(f"RTL 快照路径无效：{relative}")
            if not relative.endswith(".sv") or path.as_posix() in normalized:
                raise ValueError(f"RTL 快照路径无效或重复：{relative}")
            normalized.add(path.as_posix())
        snapshot_root = self.artifacts_dir / "rtl_snapshots" / snapshot_id
        snapshot_root.mkdir(parents=True, exist_ok=False)
        entries = []
        for relative, content in files.items():
            target = self._resolve_ref(relative, directory=snapshot_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            encoded = content.encode("utf-8")
            with target.open("xb") as output:
                output.write(encoded)
            entries.append({
                "path": relative,
                "artifact": self.artifact_ref(target),
                "bytes": len(encoded),
                "sha256": hashlib.sha256(encoded).hexdigest(),
            })
        return {"files": entries}

    def read_text_artifact(self, reference: str) -> str:
        path = self._resolve_ref(reference)
        if not path.is_file():
            raise FileNotFoundError(f"artifact 不存在：{reference}")
        return path.read_text(encoding="utf-8")

    def read_json_artifact(self, reference: str) -> Any:
        try:
            return json.loads(self.read_text_artifact(reference))
        except json.JSONDecodeError as error:
            raise ValueError(f"artifact 不是合法 JSON：{reference}") from error

    def write_handoff(
        self,
        source: str,
        target: str,
        payload: dict[str, Any],
        *,
        attempt: int | None = None,
        label: str = "",
    ) -> Path:
        """写出不可变交接消息；大内容必须通过 payload.artifacts 传递引用。"""
        if not isinstance(payload, dict):
            raise ValueError("handoff payload 必须是对象")
        edge_id = f"{source}_to_{target}"
        record = {
            "schema_version": 1,
            "edge_id": edge_id,
            "source": source,
            "target": target,
            "attempt": attempt,
            "label": label,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "payload": payload,
        }
        suffix = f"_attempt{attempt}" if attempt is not None else ""
        path = self.handoffs_dir / f"{edge_id}{suffix}.json"
        if path.exists():
            raise ValueError(f"handoff 已存在，拒绝覆盖：{path.name}")
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def read_handoff(self, path: Path) -> dict[str, Any]:
        """读取并校验由上游 Agent 明确传来的 handoff。"""
        resolved = path.resolve()
        root = self.handoffs_dir.resolve()
        if root not in resolved.parents or not resolved.is_file():
            raise ValueError("handoff 路径无效")
        try:
            record = json.loads(resolved.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"handoff 不是合法 JSON：{path.name}") from error
        if not isinstance(record, dict) or record.get("schema_version") != 1:
            raise ValueError(f"handoff schema 不兼容：{path.name}")
        if not isinstance(record.get("payload"), dict):
            raise ValueError(f"handoff 缺少 payload：{path.name}")
        return record


class SubAgent:
    name = "subagent"
    title = "SubAgent"
    node_type = "model"

    def __init__(self, context: RunContext) -> None:
        self.runtime = context
        self.base_dir = context.run_dir / "agents" / self.name
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.context_path = self.base_dir / "context.json"
        self.context: dict[str, Any] = self.load_context()

    def load_context(self) -> dict[str, Any]:
        if not self.context_path.is_file():
            return {}
        try:
            payload = json.loads(self.context_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def save_context(self, **updates: Any) -> None:
        self.context.update(updates)
        self.context_path.write_text(
            json.dumps(self.context, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def check_cancel(self) -> None:
        self.runtime.check_cancel()

    def finish(self, event: dict[str, Any], status: str, **fields: Any) -> None:
        self.runtime.finish_event(event, status, **fields)

#!/usr/bin/env python3
"""Build runtime-native AskUser actions from clarification requests."""

from __future__ import annotations


def request_user_input_questions(requests: list[dict]) -> list[dict]:
    questions: list[dict] = []
    for request in requests:
        options = [
            {
                "label": str(option.get("label", "")).strip(),
                "description": str(option.get("description", "")).strip(),
            }
            for option in request.get("options", []) or []
            if isinstance(option, dict)
        ]
        questions.append(
            {
                "header": str(request.get("header", "Clarify")).strip() or "Clarify",
                "id": str(request.get("id", "clarify_requirement")).strip() or "clarify_requirement",
                "question": str(request.get("question", "")).strip(),
                "options": options,
            }
        )
    return questions


def request_user_input_action(requests: list[dict]) -> dict:
    return {
        "schema": "codex.request_user_input.v1",
        "tool": "request_user_input",
        "required": bool(requests),
        "arguments": {"questions": request_user_input_questions(requests)},
        "source_requests": requests,
        "response_handling": [
            "Ask the user with request_user_input when available.",
            "Record selected answers with confirmed-by: user @<date/session/artifact> provenance.",
            "Update the design doc before rerunning clarify or dispatching downstream phases.",
        ],
    }

# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from typing import TypedDict


class RpcCommand(TypedDict, total=False):
    id: str
    type: str
    message: str
    enabled: bool
    level: str
    customInstructions: str
    outputPath: str
    sessionPath: str
    name: str


class RpcResponse(TypedDict, total=False):
    id: str
    type: str
    command: str
    success: bool
    data: object
    error: str

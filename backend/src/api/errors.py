"""API 错误类型与统一处理。"""
from __future__ import annotations


class ApiException(Exception):
    """携带结构化错误码的异常，由全局处理器转换为统一信封。"""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def invalid_parameter(message: str) -> ApiException:
    return ApiException(400, "INVALID_PARAMETER", message)


def resource_not_found(message: str = "资源不存在") -> ApiException:
    return ApiException(404, "RESOURCE_NOT_FOUND", message)


def run_not_found(message: str = "未找到指定的 run_id") -> ApiException:
    return ApiException(404, "RUN_NOT_FOUND", message)


def trade_not_found(message: str = "未找到指定的 trade_id") -> ApiException:
    return ApiException(404, "TRADE_NOT_FOUND", message)


def trade_not_cancellable(message: str = "该交易非当日交易或已撤销，无法撤销") -> ApiException:
    return ApiException(409, "TRADE_NOT_CANCELLABLE", message)

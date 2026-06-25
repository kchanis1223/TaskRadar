from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NotificationPreview:
    channel: str
    send_time: str
    message: str
    delivered: bool = False


class PreviewNotificationProvider:
    def build_preview(self, message: str, send_time: str = "매일 오전 8시") -> NotificationPreview:
        return NotificationPreview(
            channel="카카오톡 나에게 보내기 미리보기",
            send_time=send_time,
            message=message,
            delivered=False,
        )


class KakaoMemoNotificationProvider:
    """Placeholder for local phase 2 Kakao OAuth + memo send implementation."""

    def send(self, message: str) -> None:
        raise NotImplementedError("카카오 나에게 보내기 실제 발송은 2차 확장 범위입니다.")

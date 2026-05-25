from abc import ABC, abstractmethod
from typing import Optional
import stripe
from app.platform.config.settings import settings

class PaymentProvider(ABC):
    @abstractmethod
    async def create_checkout_session(
        self,
        customer_id: Optional[str],
        price_id: str,
        success_url: str,
        cancel_url: str,
        metadata: dict
    ) -> str:
        """Возвращает URL Checkout Session"""
        pass

    @abstractmethod
    async def handle_webhook(self, payload: bytes, signature: str) -> dict:
        """Обрабатывает событие от провайдера, возвращает данные"""
        pass

    @abstractmethod
    async def cancel_subscription(self, subscription_id: str) -> bool:
        """Отменяет подписку в платёжной системе"""
        pass

class StripeProvider(PaymentProvider):
    def __init__(self):
        stripe.api_key = settings.stripe_secret_key
        self.webhook_secret = settings.stripe_webhook_secret

    async def create_checkout_session(self, customer_id, price_id, success_url, cancel_url, metadata):
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{
                "price": price_id,
                "quantity": 1,
            }],
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=metadata,
        )
        return session.url

    async def handle_webhook(self, payload: bytes, sig_header: str):
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, self.webhook_secret
            )
        except ValueError:
            raise ValueError("Invalid payload")
        except stripe.error.SignatureVerificationError:
            raise ValueError("Invalid signature")
        return event

    async def cancel_subscription(self, subscription_id: str):
        try:
            stripe.Subscription.delete(subscription_id)
            return True
        except Exception:
            return False
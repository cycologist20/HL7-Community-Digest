"""AWS SES email sender for digest delivery."""

import logging
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from ..config import EmailConfig

logger = logging.getLogger(__name__)


class EmailError(Exception):
    """Exception raised when email delivery fails."""
    
    pass


class SESSender:
    """Sends digest emails via AWS SES."""
    
    def __init__(self, config: Optional[EmailConfig] = None) -> None:
        """Initialize the SES sender.
        
        Args:
            config: Email configuration. Loads from env if not provided.
        """
        if config is None:
            from ..config import get_config
            config = get_config().email
        
        self.config = config
        self.client = boto3.client("ses", region_name=config.aws_region)
    
    def send_digest(
        self,
        subject: str,
        body_text: str,
        recipients: Optional[list[str]] = None,
        dry_run: bool = False,
    ) -> dict:
        """Send digest email to recipients.
        
        Args:
            subject: Email subject line.
            body_text: Plain text email body.
            recipients: List of recipient emails. Uses config if not provided.
            dry_run: If True, log but don't actually send.
            
        Returns:
            Dict with 'success', 'message_id', and 'recipients' keys.
            
        Raises:
            EmailError: If sending fails.
        """
        if recipients is None:
            recipients = self.config.recipients
        
        if not recipients:
            raise EmailError("No recipients configured")
        
        logger.info(f"Sending digest to {len(recipients)} recipient(s)")
        
        if dry_run:
            logger.info("DRY RUN - Email would be sent:")
            logger.info(f"  From: {self.config.sender_email}")
            logger.info(f"  To: {', '.join(recipients)}")
            logger.info(f"  Subject: {subject}")
            logger.info(f"  Body length: {len(body_text)} chars")
            return {
                "success": True,
                "message_id": "dry-run",
                "recipients": recipients,
            }
        
        try:
            response = self.client.send_email(
                Source=self.config.sender_email,
                Destination={
                    "ToAddresses": recipients,
                },
                Message={
                    "Subject": {
                        "Data": subject,
                        "Charset": "UTF-8",
                    },
                    "Body": {
                        "Text": {
                            "Data": body_text,
                            "Charset": "UTF-8",
                        },
                    },
                },
            )
            
            message_id = response.get("MessageId", "unknown")
            logger.info(f"Email sent successfully. MessageId: {message_id}")
            
            return {
                "success": True,
                "message_id": message_id,
                "recipients": recipients,
            }
            
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            
            logger.error(f"SES error ({error_code}): {error_message}")
            
            # Provide helpful guidance for common errors
            if error_code == "MessageRejected":
                logger.error(
                    "Email was rejected. Ensure sender email is verified in SES."
                )
            elif error_code == "InvalidParameterValue":
                logger.error(
                    "Invalid email address. Check recipient addresses."
                )
            elif error_code == "MailFromDomainNotVerified":
                logger.error(
                    f"Domain not verified. Verify {self.config.sender_email.split('@')[1]} in SES."
                )
            
            raise EmailError(f"Failed to send email: {error_message}") from e
    
    def verify_sender(self) -> bool:
        """Verify that the sender email is configured in SES.
        
        Returns:
            True if sender is verified, False otherwise.
        """
        try:
            # Check if we can send from this address
            response = self.client.get_identity_verification_attributes(
                Identities=[self.config.sender_email]
            )
            
            attrs = response.get("VerificationAttributes", {})
            sender_attrs = attrs.get(self.config.sender_email, {})
            status = sender_attrs.get("VerificationStatus")
            
            if status == "Success":
                logger.info(f"Sender {self.config.sender_email} is verified")
                return True
            else:
                logger.warning(
                    f"Sender {self.config.sender_email} verification status: {status}"
                )
                return False
                
        except ClientError as e:
            logger.error(f"Failed to check sender verification: {e}")
            return False
    
    def request_sender_verification(self) -> bool:
        """Request verification for the sender email.
        
        Returns:
            True if verification request was sent, False otherwise.
        """
        try:
            self.client.verify_email_identity(
                EmailAddress=self.config.sender_email
            )
            logger.info(
                f"Verification email sent to {self.config.sender_email}. "
                "Check inbox and click verification link."
            )
            return True
            
        except ClientError as e:
            logger.error(f"Failed to request verification: {e}")
            return False

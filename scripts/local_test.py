#!/usr/bin/env python
"""Local testing script for HL7 Community Digest.

Usage:
    python scripts/local_test.py                    # Generate digest (dry run)
    python scripts/local_test.py --send-email       # Generate and send
    python scripts/local_test.py --scrape-only      # Just test scraping
    python scripts/local_test.py --test-email       # Test email delivery only
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Add src to path for local development
sys.path.insert(0, str(Path(__file__).parent.parent))


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for local testing."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Also set level for our modules
    logging.getLogger("src").setLevel(level)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def test_scraping(config) -> None:
    """Test Confluence scraping only."""
    from src.scrapers.confluence import ConfluenceScraper
    
    print("\n" + "=" * 60)
    print("Testing Confluence Scraping")
    print("=" * 60)
    
    scraper = ConfluenceScraper(timeout=60)  # Increased timeout
    
    total_sources = len(config.sources.confluence)
    print(f"\nFound {total_sources} Confluence sources to scrape\n")
    
    for i, source in enumerate(config.sources.confluence, 1):
        print(f"\n[{i}/{total_sources}] Scraping: {source.name}")
        print(f"    Work Group: {source.work_group}")
        print(f"    URL: {source.url}")
        print(f"    Fetching page...", end=" ", flush=True)
        
        start_time = time.time()
        
        try:
            content = scraper.scrape_source(source)
            elapsed = time.time() - start_time
            
            if content:
                print(f"Done! ({elapsed:.1f}s)")
                print(f"    ✅ Success!")
                print(f"    Title: {content.title}")
                print(f"    Content length: {len(content.content)} chars")
                if content.last_modified:
                    print(f"    Last modified: {content.last_modified}")
                if content.action_items:
                    print(f"    Action items found: {len(content.action_items)}")
                if content.decisions:
                    print(f"    Decisions found: {len(content.decisions)}")
                
                # Show preview
                preview = content.content[:300].replace('\n', ' ')
                if len(content.content) > 300:
                    preview += "..."
                print(f"    Preview: {preview}")
            else:
                print(f"Failed! ({elapsed:.1f}s)")
                print(f"    ❌ Failed to scrape (returned None)")
                
        except KeyboardInterrupt:
            print("\n\nInterrupted by user.")
            sys.exit(1)
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"Error! ({elapsed:.1f}s)")
            print(f"    ❌ Exception: {type(e).__name__}: {e}")
    
    print("\n" + "=" * 60)
    print("Scraping test complete!")
    print("=" * 60)


def test_single_page() -> None:
    """Test scraping a single page with detailed output."""
    import requests
    
    print("\n" + "=" * 60)
    print("Testing Single Page Scrape (Argonaut - simpler page)")
    print("=" * 60)
    
    # Use the Argonaut page as it's likely simpler
    url = "https://confluence.hl7.org/spaces/AP/pages/325451819/2025+Projects"
    
    print(f"\nURL: {url}")
    
    # Browser-like headers
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    
    print("\nStep 1: Testing with browser-like headers...")
    print(f"    User-Agent: {headers['User-Agent'][:50]}...")
    
    start_time = time.time()
    
    try:
        print("    Sending HTTP GET request...", flush=True)
        
        response = requests.get(url, timeout=60, headers=headers)
        
        elapsed = time.time() - start_time
        print(f"    Response received! ({elapsed:.1f}s)")
        print(f"    Status code: {response.status_code}")
        print(f"    Content length: {len(response.text)} bytes")
        print(f"    Content type: {response.headers.get('content-type', 'unknown')}")
        
        if response.status_code == 200:
            print("\n✅ Page fetch successful!")
            
            print("\nStep 2: Parsing HTML...")
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, "lxml")
            
            title = soup.find("title")
            print(f"    Page title: {title.get_text() if title else 'Not found'}")
            
            # Check for main content
            main_content = soup.select_one("#main-content")
            if main_content:
                print(f"    Found #main-content element")
                text = main_content.get_text(strip=True)[:500]
                print(f"    Content preview: {text}...")
            else:
                print("    #main-content not found, checking body...")
                body = soup.find("body")
                if body:
                    text = body.get_text(strip=True)[:500]
                    print(f"    Body preview: {text}...")
                    
        elif response.status_code == 405:
            print(f"\n❌ HTTP 405 Method Not Allowed")
            print("\n    The server is rejecting our request.")
            print("    Let's check what the response body says...")
            print(f"\n    Response preview:\n{response.text[:500]}")
            
            # Try to see if there's a specific error message
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, "lxml")
            error_msg = soup.find("title")
            if error_msg:
                print(f"\n    Error title: {error_msg.get_text()}")
        else:
            print(f"\n❌ HTTP error: {response.status_code}")
            
    except requests.exceptions.Timeout:
        print(f"\n❌ Request timed out after 60 seconds")
    except requests.exceptions.ConnectionError as e:
        print(f"\n❌ Connection error: {e}")
    except Exception as e:
        print(f"\n❌ Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()


def test_scraper_class() -> None:
    """Test the actual ConfluenceScraper class."""
    from src.scrapers.confluence import ConfluenceScraper
    from src.config import ConfluenceSource
    
    print("\n" + "=" * 60)
    print("Testing ConfluenceScraper Class")
    print("=" * 60)
    
    # Create a test source
    source = ConfluenceSource(
        name="Argonaut 2025 Projects",
        work_group="Argonaut",
        url="https://confluence.hl7.org/spaces/AP/pages/325451819/2025+Projects"
    )
    
    print(f"\nSource: {source.name}")
    print(f"URL: {source.url}")
    
    print("\nStep 1: Creating scraper with browser headers...")
    scraper = ConfluenceScraper(timeout=60)
    print("    Done!")
    
    print("\nStep 2: Scraping page using scraper class...")
    start_time = time.time()
    
    try:
        content = scraper.scrape_source(source)
        elapsed = time.time() - start_time
        
        if content:
            print(f"\n✅ Success! ({elapsed:.1f}s)")
            print(f"    Title: {content.title}")
            print(f"    Content length: {len(content.content)} chars")
            print(f"    Last modified: {content.last_modified}")
            print(f"\n    Content preview:")
            print(f"    {content.content[:500]}...")
        else:
            print(f"\n❌ Scraper returned None ({elapsed:.1f}s)")
            
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n❌ Exception ({elapsed:.1f}s): {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()


def test_email(config, dry_run: bool = True) -> None:
    """Test email delivery."""
    from src.delivery import SESSender
    
    print("\n" + "=" * 60)
    print("Testing Email Delivery")
    print("=" * 60)
    
    sender = SESSender(config.email)
    
    # Check sender verification
    print(f"\nSender: {config.email.sender_email}")
    print(f"Recipients: {', '.join(config.email.recipients)}")
    
    if not dry_run:
        print("\nVerifying sender...")
        if sender.verify_sender():
            print("  ✅ Sender is verified")
        else:
            print("  ⚠️  Sender not verified. Run with --verify-sender to request verification.")
            return
    
    # Send test email
    print(f"\nSending test email (dry_run={dry_run})...")
    
    result = sender.send_digest(
        subject="[TEST] HL7 Community Digest - Test Email",
        body_text="This is a test email from the HL7 Community Digest system.\n\nIf you received this, email delivery is working!",
        dry_run=dry_run,
    )
    
    if result["success"]:
        print(f"  ✅ {'Would send' if dry_run else 'Sent'} to: {', '.join(result['recipients'])}")
        if not dry_run:
            print(f"  Message ID: {result['message_id']}")
    else:
        print("  ❌ Failed to send")


def run_full_digest(dry_run: bool = True) -> None:
    """Run full digest generation."""
    from src.main import DigestOrchestrator
    
    print("\n" + "=" * 60)
    print("Running Full Digest Generation")
    print("=" * 60)
    
    orchestrator = DigestOrchestrator()
    result = orchestrator.run(dry_run=dry_run)
    
    if result["success"]:
        print("\n✅ Digest generated successfully!")
        print(f"\nStats:")
        print(f"  Confluence pages: {result['stats']['confluence_pages_scraped']}")
        print(f"  Zulip threads: {result['stats']['zulip_threads_scraped']}")
        print(f"  Elapsed time: {result['stats']['elapsed_seconds']:.1f}s")
        
        # Show digest content
        print("\n" + "-" * 60)
        print("DIGEST CONTENT:")
        print("-" * 60)
        print(result["digest"].to_plain_text())
    else:
        print("\n❌ Digest generation failed")


def verify_sender_email(config) -> None:
    """Request sender email verification."""
    from src.delivery import SESSender
    
    print("\n" + "=" * 60)
    print("Requesting Sender Verification")
    print("=" * 60)
    
    sender = SESSender(config.email)
    
    print(f"\nSender: {config.email.sender_email}")
    
    if sender.request_sender_verification():
        print("✅ Verification email sent. Check your inbox and click the link.")
    else:
        print("❌ Failed to request verification")


def main():
    parser = argparse.ArgumentParser(description="HL7 Community Digest - Local Testing")
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "--scrape-only",
        action="store_true",
        help="Only test Confluence scraping"
    )
    parser.add_argument(
        "--test-single",
        action="store_true",
        help="Test scraping a single page with detailed output"
    )
    parser.add_argument(
        "--test-scraper",
        action="store_true",
        help="Test the ConfluenceScraper class directly"
    )
    parser.add_argument(
        "--test-email",
        action="store_true",
        help="Test email delivery"
    )
    parser.add_argument(
        "--send-email",
        action="store_true",
        help="Actually send the digest email (not dry run)"
    )
    parser.add_argument(
        "--verify-sender",
        action="store_true",
        help="Request sender email verification"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Dry run mode (default)"
    )
    
    args = parser.parse_args()
    
    # Setup
    setup_logging(args.verbose)
    
    print("=" * 60)
    print("HL7 Community Digest - Local Testing")
    print("=" * 60)
    
    # Quick test for single page (most useful for debugging)
    if args.test_single:
        test_single_page()
        return
    
    # Test the scraper class directly
    if args.test_scraper:
        test_scraper_class()
        return
    
    # Load config for other tests
    from src.config import load_config
    config = load_config()
    
    print(f"\nConfiguration loaded:")
    print(f"  Confluence sources: {len(config.sources.confluence)}")
    print(f"  Zulip sources: {len(config.sources.zulip)}")
    print(f"  Confluence enabled: {config.processing.enable_confluence}")
    print(f"  Zulip enabled: {config.processing.enable_zulip}")
    
    # Determine dry_run setting
    dry_run = not args.send_email
    
    # Run requested tests
    if args.verify_sender:
        verify_sender_email(config)
    elif args.scrape_only:
        test_scraping(config)
    elif args.test_email:
        test_email(config, dry_run=dry_run)
    else:
        # Full digest
        run_full_digest(dry_run=dry_run)


if __name__ == "__main__":
    main()

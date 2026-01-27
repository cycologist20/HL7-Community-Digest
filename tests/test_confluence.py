"""Tests for Confluence scraper."""

import pytest
import responses
from datetime import datetime

from src.scrapers.confluence import ConfluenceScraper, ScraperError
from src.config import ConfluenceSource


# Sample Confluence HTML for testing
SAMPLE_CONFLUENCE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Burden Reduction Wednesday Meeting Minutes - HL7 Confluence</title>
    <meta name="ajs-last-modified-date" content="2025-01-20T15:30:00Z">
</head>
<body>
    <div id="main-content">
        <h1>Burden Reduction Wednesday Meeting Minutes</h1>
        <h2>January 15, 2025</h2>
        <p>Attendees: John Smith, Jane Doe, Bob Wilson</p>
        <h3>Discussion Topics</h3>
        <ul>
            <li>CRD implementation timeline review</li>
            <li>DTR workflow clarifications</li>
        </ul>
        <h3>Decisions</h3>
        <p>Decision: Extend Q2 milestone by two weeks due to testing delays.</p>
        <h3>Action Items</h3>
        <p>Action: John to update the implementation guide by January 22.</p>
        <p>Action: Jane to schedule follow-up meeting with payers.</p>
    </div>
</body>
</html>
"""


class TestConfluenceScraper:
    """Tests for ConfluenceScraper class."""
    
    def test_init_default_timeout(self):
        """Test scraper initializes with default timeout."""
        scraper = ConfluenceScraper()
        assert scraper.timeout == 30
    
    def test_init_custom_timeout(self):
        """Test scraper initializes with custom timeout."""
        scraper = ConfluenceScraper(timeout=60)
        assert scraper.timeout == 60
    
    @responses.activate
    def test_scrape_page_success(self):
        """Test successful page scraping."""
        url = "https://confluence.hl7.org/test-page"
        
        responses.add(
            responses.GET,
            url,
            body=SAMPLE_CONFLUENCE_HTML,
            status=200,
            content_type="text/html",
        )
        
        scraper = ConfluenceScraper()
        result = scraper.scrape_page(url, "Da Vinci", "Test Page")
        
        assert result is not None
        assert result.work_group == "Da Vinci"
        assert result.source_name == "Test Page"
        assert result.url == url
        assert "Burden Reduction" in result.title
        assert "CRD implementation" in result.content
    
    @responses.activate
    def test_scrape_page_extracts_decisions(self):
        """Test that decisions are extracted from content."""
        url = "https://confluence.hl7.org/test-page"
        
        responses.add(
            responses.GET,
            url,
            body=SAMPLE_CONFLUENCE_HTML,
            status=200,
        )
        
        scraper = ConfluenceScraper()
        result = scraper.scrape_page(url, "Da Vinci")
        
        assert result is not None
        assert len(result.decisions) > 0
        assert any("Q2 milestone" in d for d in result.decisions)
    
    @responses.activate
    def test_scrape_page_extracts_action_items(self):
        """Test that action items are extracted from content."""
        url = "https://confluence.hl7.org/test-page"
        
        responses.add(
            responses.GET,
            url,
            body=SAMPLE_CONFLUENCE_HTML,
            status=200,
        )
        
        scraper = ConfluenceScraper()
        result = scraper.scrape_page(url, "Da Vinci")
        
        assert result is not None
        assert len(result.action_items) >= 2
    
    @responses.activate
    def test_scrape_page_404_returns_none(self):
        """Test that 404 response returns None."""
        url = "https://confluence.hl7.org/not-found"
        
        responses.add(
            responses.GET,
            url,
            status=404,
        )
        
        scraper = ConfluenceScraper()
        result = scraper.scrape_page(url, "Da Vinci")
        
        assert result is None
    
    @responses.activate
    def test_scrape_source(self):
        """Test scraping from a ConfluenceSource config."""
        source = ConfluenceSource(
            name="Test Meeting Minutes",
            work_group="CDS",
            url="https://confluence.hl7.org/cds-page",
            description="Test description",
        )
        
        responses.add(
            responses.GET,
            source.url,
            body=SAMPLE_CONFLUENCE_HTML,
            status=200,
        )
        
        scraper = ConfluenceScraper()
        result = scraper.scrape_source(source)
        
        assert result is not None
        assert result.source_name == source.name
        assert result.work_group == source.work_group
    
    @responses.activate
    def test_scrape_all_partial_success(self):
        """Test scraping multiple sources with partial failures."""
        sources = [
            ConfluenceSource(
                name="Page 1",
                work_group="Da Vinci",
                url="https://confluence.hl7.org/page1",
            ),
            ConfluenceSource(
                name="Page 2",
                work_group="CDS",
                url="https://confluence.hl7.org/page2",
            ),
        ]
        
        # First succeeds, second fails
        responses.add(
            responses.GET, 
            sources[0].url, 
            body=SAMPLE_CONFLUENCE_HTML, 
            status=200
        )
        responses.add(
            responses.GET, 
            sources[1].url, 
            status=500
        )
        
        scraper = ConfluenceScraper()
        results = scraper.scrape_all(sources)
        
        # Should return only successful scrapes
        assert len(results) == 1
        assert results[0].source_name == "Page 1"

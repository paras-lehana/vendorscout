# ============================================================
# VendorScout Pro - SerperDev Search Tool
# ============================================================
# Wrapper for SerperDev Google Search API.
# Used for initial vendor discovery and news/review searches.
# SerperDev provides structured Google search results as JSON.
#
# See: https://serper.dev/
# ============================================================

import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class SearchResult:
    """A single search result from SerperDev."""
    def __init__(self, title: str, url: str, snippet: str, position: int = 0):
        self.title = title
        self.url = url
        self.snippet = snippet
        self.position = position
    
    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "position": self.position
        }


class SearchTool:
    """
    Google Search via SerperDev API.
    
    Returns structured search results for vendor discovery,
    news monitoring, and review aggregation queries.
    
    Usage:
        tool = SearchTool()
        results = await tool.search("ISO 27001 cloud security vendors Europe")
    """
    
    def __init__(self):
        self.api_key = settings.SERPER_API_KEY
        self.base_url = "https://google.serper.dev"
    
    async def search(
        self,
        query: str,
        num_results: int = 10,
        search_type: str = "search",
        gl: str = None,  # Geographic location (country code)
        hl: str = "en"   # Language
    ) -> list[SearchResult]:
        """
        Execute a Google search via SerperDev.
        
        Args:
            query: Search query string
            num_results: Number of results to return (max 100)
            search_type: "search" (web), "news", "images"
            gl: Country code for geo-targeting (e.g., "us", "de", "in")
            hl: Language for results
            
        Returns:
            List of SearchResult objects
        """
        try:
            headers = {
                "X-API-KEY": self.api_key,
                "Content-Type": "application/json"
            }
            
            payload = {
                "q": query,
                "num": min(num_results, 100),
                "hl": hl
            }
            
            if gl:
                payload["gl"] = gl
            
            endpoint = f"{self.base_url}/{search_type}"
            
            logger.info(f"SerperDev search: '{query[:80]}...' ({search_type}, {num_results} results)")
            
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    endpoint,
                    headers=headers,
                    json=payload
                )
                
                if response.status_code != 200:
                    logger.error(f"SerperDev error {response.status_code}: {response.text[:300]}")
                    return []
                
                data = response.json()
            
            results = []
            
            # Parse organic results
            organic = data.get("organic", [])
            for i, item in enumerate(organic):
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("link", ""),
                    snippet=item.get("snippet", ""),
                    position=i + 1
                ))
            
            # For news searches, use news results
            if search_type == "news":
                news = data.get("news", [])
                for i, item in enumerate(news):
                    results.append(SearchResult(
                        title=item.get("title", ""),
                        url=item.get("link", ""),
                        snippet=item.get("snippet", item.get("description", "")),
                        position=i + 1
                    ))
            
            logger.info(f"SerperDev returned {len(results)} results for '{query[:50]}...'")
            return results
            
        except httpx.TimeoutException:
            logger.error(f"SerperDev timeout for query: {query[:80]}")
            return []
        except Exception as e:
            logger.error(f"SerperDev error: {e}")
            return []
    
    async def search_news(self, query: str, num_results: int = 10) -> list[SearchResult]:
        """Convenience method for news-specific searches."""
        return await self.search(query, num_results, search_type="news")

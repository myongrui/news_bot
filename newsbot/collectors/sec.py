from __future__ import annotations

import httpx

from newsbot.collectors.base import BaseCollector, CollectorResult
from newsbot.types import RawItem
from newsbot.utils import parse_datetime


class SecCollector(BaseCollector):
    async def collect(self, client: httpx.AsyncClient) -> CollectorResult:
        try:
            forms = {str(form).upper() for form in self.source.options.get("forms", [])}
            tickers = [ticker for ticker in self.config.tickers if ticker.cik]
            items: list[RawItem] = []
            for ticker in tickers:
                cik = str(ticker.cik).zfill(10)
                url = f"https://data.sec.gov/submissions/CIK{cik}.json"
                response = await client.get(url)
                if response.status_code >= 400:
                    continue
                data = response.json()
                recent = data.get("filings", {}).get("recent", {})
                accession_numbers = recent.get("accessionNumber", [])
                form_values = recent.get("form", [])
                filing_dates = recent.get("filingDate", [])
                primary_docs = recent.get("primaryDocument", [])
                for index, accession in enumerate(accession_numbers[:40]):
                    form = str(form_values[index]).upper() if index < len(form_values) else ""
                    if forms and form not in forms:
                        continue
                    primary_doc = primary_docs[index] if index < len(primary_docs) else ""
                    accession_path = str(accession).replace("-", "")
                    filing_url = (
                        "https://www.sec.gov/Archives/edgar/data/"
                        f"{int(cik)}/{accession_path}/{primary_doc}"
                    )
                    filing_date = filing_dates[index] if index < len(filing_dates) else None
                    title = f"{ticker.symbol} {form} filing"
                    items.append(
                        RawItem(
                            source_id=self.source.id,
                            external_id=f"{ticker.symbol}:{accession}",
                            title=title,
                            url=filing_url,
                            published_at=parse_datetime(filing_date),
                            author=ticker.name,
                            payload={
                                "connector": "sec",
                                "ticker": ticker.symbol,
                                "cik": cik,
                                "form": form,
                                "accession_number": accession,
                                "company": ticker.name,
                            },
                        )
                    )
            return CollectorResult(items=items)
        except Exception as exc:  # noqa: BLE001
            return self.failed(exc)


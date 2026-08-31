# Hard step cap instead of resumable crawl

OpenRouter's free tier caps usage at 50 requests/day with no purchased credits, and the Navigator/Writer calls both run against a free model. Rather than persist the Flow Graph mid-Crawl and resume across days once the daily cap is hit, the Crawl simply hard-stops at ~40 Screens per run. Simpler for an MVP; revisit with day-spanning persistence if a target app's screen count regularly exceeds the free-tier budget.

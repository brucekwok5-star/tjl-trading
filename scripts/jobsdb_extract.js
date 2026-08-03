() => {
  const cards = document.querySelectorAll('[data-testid="job-card"], article[data-job-id]');
  const r = [];
  for (const c of cards) {
    const jobId = c.dataset.jobId || '';
    const rawAria = c.getAttribute('aria-label') || '';
    // aria-label includes "at Company Name" suffix - strip it
    const title = rawAria.replace(/\s+at\s+.+$/i, '').trim();

    // Company
    const logoLink = c.querySelector('[data-testid="job-card-company-logo-link"]');
    let company = 'N/A';
    if (logoLink) {
      const href = logoLink.getAttribute('href', 2) || '';
      const parts = href.split('/');
      if (parts.length >= 3) {
        const slug = decodeURIComponent(parts[2]);
        company = slug.replace(/-[0-9]+$/, '').replace(/-/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
      }
    }

    // Build full innerText to extract structured fields
    const fullText = c.innerText || '';

    // Location - find first geo match
    const geoPatterns = [
      /(?:Hong Kong|Kowloon|New Territories|Remote|Hybrid|Tai Po|Sha Tin|Central|Sheung Wan|Wan Chai|Causeway Bay|Mong Kok|Tsim Sha Tsui|Kwun Tong|San Po Kong|Quarry Bay|Clear Water Bay|Sai Kung|Stanley|Pokfulam| Mid-Levels)[^\n]*/i,
      /[A-Z][a-z]+(?: Bay|Town|Central|Kowloon)[^\n]*/,
    ];
    let location = 'N/A';
    for (const p of geoPatterns) {
      const m = fullText.match(p);
      if (m) { location = m[0].trim().slice(0, 80); break; }
    }

    // Posted
    const postedEl = c.querySelector('[class*="hkui540"]');
    const posted = postedEl ? postedEl.innerText.trim() : 'N/A';

    // Salary
    const salaryPatterns = [
      /HK\$[\d,]+(?:\.\d+)?(?:K|M)?(?:\s*-\s*HK\$[\d,]+(?:K|M)?)?/,
      /HKD\s*[\d,]+(?:\.\d+)?[KMB]?/,
      /\$[\d,]+(?:\.\d+)?\s*(?:K|M)\s*(?:\/month|\/annum|\/year)?/,
      /Up to\s+\$[\d,]+/,
      /From\s+\$[\d,]+/,
      /[\d,]+(?:\.\d+)?\s*(?:K|M)\s*(?:\/month|\/annum)/,
    ];
    let salary = 'N/A';
    for (const p of salaryPatterns) {
      const m = fullText.match(p);
      if (m) { salary = m[0].trim().slice(0, 50); break; }
    }

    // Link
    const jobLink = c.querySelector('[data-automation="job-list-view-job-link"]') ||
                    c.querySelector('[data-testid="job-list-item-link-overlay"]');
    const linkSuffix = jobLink ? jobLink.getAttribute('href', 2) : `/job/${jobId}`;
    const link = linkSuffix.startsWith('http') ? linkSuffix : 'https://hk.jobsdb.com' + linkSuffix;

    if (title) {
      r.push({ title, company, location, posted, salary, source: 'JobsDB', link });
    }
  }
  return { total: r.length, jobs: r };
}

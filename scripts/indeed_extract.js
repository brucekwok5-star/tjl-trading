() => {
  // Indeed renders jobs in a flat list accessible via aria
  // Look for the main results container and extract accessible job links
  const allLinks = Array.from(document.querySelectorAll('a'));
  const jobLinks = allLinks.filter(a => {
    const href = a.href || '';
    return href.includes('/job/') || href.includes('rc.clk') || a.dataset.jobid;
  });

  const results = [];
  const seen = new Set();

  // Try to find job cards via multiple methods
  const jobCards = document.querySelectorAll('[data-jobid], .job-card, [class*="jobCard"], [class*="result-item"]');

  for (const card of jobCards) {
    const jobId = card.dataset.jobid || '';
    let title = '', company = '', location = '', salary = 'N/A', posted = 'N/A', link = '';

    // Title: look for heading or title class
    const titleEl = card.querySelector('h2, h3, [class*="title"], [class*="jobTitle"], [class*="job-title"], [data-testid="job-title"]');
    if (titleEl) title = titleEl.innerText.trim();

    // Fallback: aria-label
    if (!title) title = (card.getAttribute('aria-label') || '').split(' at ')[0].trim();

    // Company
    const companyEl = card.querySelector('[class*="company"], [class*="employer"], [data-testid="company-name"], [class*="CompanyName"]');
    if (companyEl) company = companyEl.innerText.trim();

    // Location
    const locEl = card.querySelector('[class*="location"], [class*="geo"], [class*="area"]');
    if (locEl) location = locEl.innerText.trim();

    // Salary
    const salEl = card.querySelector('[class*="salary"], [class*="pay"], [class*="compensation"]');
    if (salEl) salary = salEl.innerText.trim();

    // Link
    const linkEl = card.querySelector('a[href*="/job/"], a[href*="rc.clk"]');
    if (linkEl) {
      link = linkEl.href;
      if (!link.startsWith('http')) link = 'https://www.indeed.com' + link;
    }

    const key = (title + company + link).trim();
    if (title && !seen.has(key)) {
      seen.add(key);
      results.push({ title: title.slice(0, 120), company: company.slice(0, 80) || 'N/A', location: location.slice(0, 80) || 'N/A', posted, salary, source: 'Indeed', link });
    }
  }

  // If no cards found, extract from page text (page is showing job details)
  if (results.length === 0) {
    const body = document.body.innerText || '';
    // Try to extract from the job detail page
    const lines = body.split('\n').map(l => l.trim()).filter(l => l.length > 0);
    let title = '', company = '', location = 'Hong Kong', link = window.location.href;

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (!title && line.length > 5 && line.length < 150 && !line.includes('Job details') && !line.includes('Apply on')) {
        if (lines[i+1] && (lines[i+1].includes('Hong Kong') || lines[i+1].includes('Permanent') || lines[i+1].includes('Contract'))) {
          title = line;
        }
      }
      if (!company && (line.includes('Limited') || line.includes('Ltd') || line.includes('Company') || line.includes('HKEX') || line.includes('Bank'))) {
        company = line.slice(0, 80);
      }
    }
    if (title) {
      results.push({ title: title.slice(0, 120), company, location, posted: 'N/A', salary: 'N/A', source: 'Indeed', link });
    }
  }

  return { total: results.length, jobs: results.slice(0, 50), url: window.location.href };
}

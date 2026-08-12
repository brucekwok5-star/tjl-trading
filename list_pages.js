// list_pages.js — list CDP pages on port 18800, find community page
const http = require('http');
const host = '127.0.0.1';
const port = 18800;
const path = '/json';

const req = http.get({hostname: host, port: port, path: path}, (res) => {
  let data = '';
  res.on('data', (chunk) => data += chunk);
  res.on('end', () => {
    try {
      const pages = JSON.parse(data);
      // Find community page
      const community = pages.find(p =>
        p.url && p.url.includes('community') && p.url.includes('futunn')
      );
      if (community) {
        process.stdout.write(community.id + '|' + community.url);
      } else {
        // No community page — return first Futu page or first page
        const futu = pages.find(p => p.url && p.url.includes('futunn'));
        const fallback = futu || pages[0];
        if (fallback) {
          process.stdout.write('NO_COMMUNITY:' + fallback.id + '|' + fallback.url);
        } else {
          process.stdout.write('NONE');
        }
      }
    } catch (e) {
      process.stderr.write('Parse error: ' + e.message);
      process.exit(1);
    }
  });
});
req.on('error', (e) => {
  process.stderr.write('HTTP error: ' + e.message);
  process.exit(1);
});

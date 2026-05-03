addEventListener('scheduled', event => {
  event.waitUntil(handleScheduled(event));
});

async function handleScheduled(event) {
  const TOKEN = GITHUB_TRIGGER_TOKEN;

  const url = `https://api.github.com/repos/songguyingfengke/tech-breakfast/actions/workflows/daily-briefing.yml/dispatches`;

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Authorization': `token ${TOKEN}`,
      'Accept': 'application/vnd.github+json',
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ ref: 'main' })
  });

  return new Response(`GitHub Actions triggered. Status: ${response.status}`, { status: response.status });
}

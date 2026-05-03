export default {
  async scheduled(event, env, ctx) {
    const GITHUB_USERNAME = env.GITHUB_USERNAME;
    const GITHUB_REPO = env.GITHUB_REPO || 'tech-breakfast';
    const GITHUB_WORKFLOW_FILE = env.GITHUB_WORKFLOW_FILE || 'daily-briefing.yml';
    const GITHUB_TOKEN = env.GITHUB_TRIGGER_TOKEN;

    const url = `https://api.github.com/repos/${GITHUB_USERNAME}/${GITHUB_REPO}/actions/workflows/${GITHUB_WORKFLOW_FILE}/dispatches`;

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': `token ${GITHUB_TOKEN}`,
        'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ ref: 'main' })
    });

    return new Response(`GitHub Actions triggered. Status: ${response.status}`, { status: response.status });
  }
};

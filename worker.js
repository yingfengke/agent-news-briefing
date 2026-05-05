// Cloudflare Workers 定时触发脚本
// Cron: 0 1 * * * (每天 UTC 01:00 = BJT 09:00)

// 定时调度
addEventListener("scheduled", (event) => {
  event.waitUntil(handleScheduled(event));
});

// 手动触发（用于测试：GET 该 Worker URL）
addEventListener("fetch", (event) => {
  event.respondWith(handleFetch(event));
});

async function handleScheduled(event) {
  return await triggerGitHubActions();
}

async function handleFetch(event) {
  const result = await triggerGitHubActions();
  return new Response(JSON.stringify(result), {
    headers: { "Content-Type": "application/json" },
  });
}

async function triggerGitHubActions() {
  const GITHUB_TOKEN = GITHUB_TRIGGER_TOKEN;
  if (!GITHUB_TOKEN) {
    return { success: false, error: "GITHUB_TRIGGER_TOKEN not configured" };
  }

  const url = "https://api.github.com/repos/songguyingfengke/tech-breakfast/actions/workflows/daily-briefing.yml/dispatches";

  try {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Authorization": `token ${GITHUB_TOKEN}`,
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: "main" }),
    });

    const success = response.status === 204 || response.status === 201;
    return {
      success: success,
      status: response.status,
      time: new Date().toISOString(),
      message: success
        ? "GitHub Actions triggered successfully"
        : `GitHub API returned ${response.status} ${response.statusText}`,
    };
  } catch (error) {
    return {
      success: false,
      error: error.message || "Unknown error",
      time: new Date().toISOString(),
    };
  }
}

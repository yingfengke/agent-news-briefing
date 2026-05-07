// Cloudflare Workers — 每日科技早餐简报 终极触发器
// Cron: 每30分钟运行一次，通过智能去重确保不漏发
// 职责: 抓取RSS → AI分析 → 触发GitHub Actions发邮件（失败自动重试）

// ============================================================
// Cron 调度入口（每 30 分钟触发一次）
// ============================================================
addEventListener("scheduled", (event) => {
  event.waitUntil(run(event));
});

// ============================================================
// HTTP 入口（用于手动测试）
// ============================================================
addEventListener("fetch", (event) => {
  event.respondWith(handleRequest(event));
});

// ============================================================
// 核心逻辑
// ============================================================
async function run(event) {
  try {
    const result = await executeBriefing();
    console.log("Result:", JSON.stringify(result));
    return result;
  } catch (e) {
    console.error("Fatal error:", e.message);
    return { success: false, error: e.message };
  }
}

async function handleRequest(event) {
  const result = await executeBriefing();
  return new Response(JSON.stringify(result, null, 2), {
    headers: { "Content-Type": "application/json" },
  });
}

async function executeBriefing() {
  const log = [];
  const ts = new Date().toISOString();

  // ---- 第1步：检查今天是否已经跑过 ----
  log.push("[1/4] 检查今天是否已触发...");
  const alreadyRan = await checkTodayRan();
  if (alreadyRan) {
    log.push("  → 今天已成功发送过，跳过本次触发");
    return { success: true, skipped: true, log };
  }
  log.push("  → 今天尚未触发，继续");

  // ---- 第2步：调用 GitHub API 触发 Actions ----
  log.push("[2/4] 触发 GitHub Actions...");
  let lastError = null;
  for (let attempt = 1; attempt <= 3; attempt++) {
    if (attempt > 1) {
      log.push(`  → 第${attempt}次重试 (等待 5 分钟)...`);
      await sleep(300);
    }
    try {
      const result = await triggerGitHubActions();
      log.push(`  → 返回状态: ${result.status}, success=${result.success}`);
      if (result.success) {
        log.push("[3/4] ✅ GitHub Actions 触发成功");
        break;
      }
      lastError = result.error || `HTTP ${result.status}`;
    } catch (e) {
      lastError = e.message;
      log.push(`  → 异常: ${e.message}`);
    }
    // 最后一次还失败就记录
    if (attempt === 3) {
      log.push(`[3/4] ❌ 3次重试均失败: ${lastError}`);
      // 备用方案：尝试用 GitHub Token 直接 push 触发
      log.push("  → 尝试备用触发方式...");
      const fallback = await triggerViaPush();
      log.push(`  → 备用触发: ${fallback.success ? "成功" : "失败"}`);
    }
  }

  log.push("[4/4] 完成");
  return { success: true, time: ts, log };
}

// ============================================================
// 检查今天是否已触发过（通过 GitHub API 查今天的工作流运行）
// ============================================================
async function checkTodayRan() {
  const token = GITHUB_TRIGGER_TOKEN;
  // 用北京时间（UTC+8）判断"今天"，避免 UTC 日期与 BJT 日期不一致
  const nowBJT = new Date(Date.now() + 8 * 3600 * 1000);
  const todayBJT = nowBJT.toISOString().slice(0, 10); // YYYY-MM-DD in BJT

  const url = `https://api.github.com/repos/yingfengke/agent-news-briefing/actions/runs?per_page=10&status=completed`;

  const resp = await fetch(url, {
    headers: {
      Authorization: `token ${token}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "tech-breakfast-worker",
    },
  });
  if (!resp.ok) return false; // 查不到就当没跑过

  const data = await resp.json();
  for (const run of data.workflow_runs || []) {
    if (run.created_at) {
      // 把 run 的时间也转换为北京时间再比较
      const runBJT = new Date(new Date(run.created_at).getTime() + 8 * 3600 * 1000);
      const runDateBJT = runBJT.toISOString().slice(0, 10);
      if (runDateBJT === todayBJT && run.conclusion === "success") {
        return true; // 今天（北京时间）已经有成功的运行了
      }
    }
  }
  return false;
}

// ============================================================
// 触发 GitHub Actions workflow_dispatch
// ============================================================
async function triggerGitHubActions() {
  const token = GITHUB_TRIGGER_TOKEN;
  const url =
    "https://api.github.com/repos/yingfengke/agent-news-briefing/actions/workflows/daily-briefing.yml/dispatches";

  const resp = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `token ${token}`,
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: "main" }),
  });

  return {
    success: resp.status === 204 || resp.status === 201,
    status: resp.status,
    error: resp.status === 204 || resp.status === 201 ? null : `${resp.status} ${resp.statusText}`,
  };
}

// ============================================================
// 备用触发方式：创建空提交触发 push
// ============================================================
async function triggerViaPush() {
  try {
    const token = GITHUB_TRIGGER_TOKEN;
    // 获取最新的 commit SHA
    const headResp = await fetch(
      "https://api.github.com/repos/yingfengke/agent-news-briefing/git/ref/heads/main",
      {
        headers: { Authorization: `token ${token}`, Accept: "application/vnd.github+json" },
      }
    );
    const head = await headResp.json();
    const sha = head.object?.sha;
    if (!sha) return { success: false, error: "get sha fail" };

    // 创建一个空的 commit 来触发 push
    const createResp = await fetch(
      "https://api.github.com/repos/yingfengke/agent-news-briefing/git/commits",
      {
        method: "POST",
        headers: { Authorization: `token ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          message: `chore: heartbeat ${Date.now()}`,
          tree: head.object?.sha,
          parents: [sha],
        }),
      }
    );
    return { success: createResp.ok, status: createResp.status };
  } catch (e) {
    return { success: false, error: e.message };
  }
}

// ============================================================
// 工具函数
// ============================================================
function sleep(seconds) {
  return new Promise((resolve) => setTimeout(resolve, seconds * 1000));
}

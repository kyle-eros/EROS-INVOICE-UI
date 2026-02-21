const { test, expect } = require("@playwright/test");

test.describe("Admin Gate", () => {
  test("submits with Enter key and transitions to admin dashboard", async ({ page }) => {
    let postedPassword = null;

    await page.route("**/api/admin/login", async (route) => {
      const body = JSON.parse(route.request().postData() || "{}");
      postedPassword = body.password;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ authenticated: true }),
      });
    });

    await page.route("**/admin", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "<html><body><h1>Admin Mock</h1></body></html>",
      });
    });

    await page.goto("/admin/gate");
    await page.getByLabel("Admin password").fill("super-secure-admin-password");
    await page.getByLabel("Admin password").press("Enter");

    await expect(page).toHaveURL(/\/admin$/);
    await expect(page.getByRole("heading", { name: "Admin Mock" })).toBeVisible();
    expect(postedPassword).toBe("super-secure-admin-password");
  });

  test("allows toggling password visibility", async ({ page }) => {
    await page.goto("/admin/gate");

    const passwordInput = page.getByLabel("Admin password");
    await expect(passwordInput).toHaveAttribute("type", "password");

    await page.getByRole("button", { name: "Show" }).click();
    await expect(passwordInput).toHaveAttribute("type", "text");

    await page.getByRole("button", { name: "Hide" }).click();
    await expect(passwordInput).toHaveAttribute("type", "password");
  });

  test("submits using autofill-like DOM value without change event", async ({ page }) => {
    let postedPassword = null;

    await page.route("**/api/admin/login", async (route) => {
      const body = JSON.parse(route.request().postData() || "{}");
      postedPassword = body.password;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ authenticated: true }),
      });
    });

    await page.route("**/admin", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "<html><body><h1>Admin Mock</h1></body></html>",
      });
    });

    await page.goto("/admin/gate");
    await page.locator("#admin-password").evaluate((element) => {
      element.value = "autofilled-admin-password";
    });
    await page.getByRole("button", { name: "Enter Dashboard" }).click();

    await expect(page).toHaveURL(/\/admin$/);
    expect(postedPassword).toBe("autofilled-admin-password");
  });

  test("renders server error message when credentials are rejected", async ({ page }) => {
    await page.route("**/api/admin/login", async (route) => {
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({
          error: "Invalid password.",
          code: "INVALID_CREDENTIALS",
        }),
      });
    });

    await page.goto("/admin/gate");
    await page.getByLabel("Admin password").fill("wrong");
    await page.getByRole("button", { name: "Enter Dashboard" }).click();

    await expect(page.locator("p.auth-feedback--error[role='alert']")).toContainText("Invalid password.");
    await expect(page).toHaveURL(/\/admin\/gate$/);
  });

  test("renders rate-limit error when backend throttles sign-in", async ({ page }) => {
    await page.route("**/api/admin/login", async (route) => {
      await route.fulfill({
        status: 429,
        contentType: "application/json",
        body: JSON.stringify({
          error: "Too many admin login attempts. Please wait and try again.",
          code: "RATE_LIMITED",
        }),
      });
    });

    await page.goto("/admin/gate");
    await page.getByLabel("Admin password").fill("any-password");
    await page.getByRole("button", { name: "Enter Dashboard" }).click();

    await expect(page.locator("p.auth-feedback--error[role='alert']")).toContainText(
      "Too many admin login attempts. Please wait and try again.",
    );
    await expect(page).toHaveURL(/\/admin\/gate$/);
  });

  test("redirects unauthenticated admin route to gate", async ({ context, page }) => {
    await context.clearCookies();

    await page.goto("/admin");

    await expect(page).toHaveURL(/\/admin\/gate$/);
    await expect(page.getByRole("heading", { name: "Admin Operations" })).toBeVisible();
  });

  test("shows one-time passkey flash without URL secret leakage", async ({ context, page }) => {
    await context.addCookies([
      {
        name: "admin_session",
        value: "test-admin-session",
        url: "http://127.0.0.1:3100",
      },
    ]);

    await page.route("**/admin/passkey-flash", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          creator_id: "creator-prime",
          creator_name: "Creator Prime",
          passkey: "flash-passkey-001",
        }),
      });
    });

    await page.goto("/admin?passkeyGen=success");
    await expect(page).toHaveURL(/\/admin\?passkeyGen=success$/);
    await expect(page).not.toHaveURL(/generatedPasskey=/);
    await expect(page.locator(".passkey-display")).toContainText("flash-passkey-001");
    await expect(page.getByRole("button", { name: "Copy passkey" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Copy creator ID" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Copy portal link" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Creator Balances" })).toBeVisible();
    await expect(page.getByText(/Creator balance data unavailable:/)).toBeVisible();
  });

  test("copies creator login artifacts from passkey flash", async ({ context, page }) => {
    await context.addCookies([
      {
        name: "admin_session",
        value: "test-admin-session",
        url: "http://127.0.0.1:3100",
      },
    ]);

    await page.addInitScript(() => {
      window.__copiedArtifacts = [];
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: {
          writeText: async (value) => {
            window.__copiedArtifacts.push(value);
          },
        },
      });
    });

    await page.route("**/admin/passkey-flash", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          creator_id: "creator-prime",
          creator_name: "Creator Prime",
          passkey: "flash-passkey-001",
        }),
      });
    });

    await page.goto("/admin?passkeyGen=success");

    await page.getByRole("button", { name: "Copy passkey" }).click();
    await expect(page.getByRole("status")).toContainText("Passkey copied.");

    await page.getByRole("button", { name: "Copy creator ID" }).click();
    await expect(page.getByRole("status")).toContainText("Creator ID copied.");

    await page.getByRole("button", { name: "Copy portal link" }).click();
    await expect(page.getByRole("status")).toContainText("Portal link copied.");

    const copiedArtifacts = await page.evaluate(() => window.__copiedArtifacts);
    expect(copiedArtifacts).toEqual([
      "flash-passkey-001",
      "creator-prime",
      "http://127.0.0.1:3100/login",
    ]);
  });

  test("shows manual fallback guidance when copy fails", async ({ context, page }) => {
    await context.addCookies([
      {
        name: "admin_session",
        value: "test-admin-session",
        url: "http://127.0.0.1:3100",
      },
    ]);

    await page.addInitScript(() => {
      window.__copyFallbackAttempts = 0;
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: undefined,
      });
      Object.defineProperty(Document.prototype, "execCommand", {
        configurable: true,
        value: () => {
          window.__copyFallbackAttempts += 1;
          return false;
        },
      });
    });

    await page.route("**/admin/passkey-flash", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          creator_id: "creator-prime",
          creator_name: "Creator Prime",
          passkey: "flash-passkey-001",
        }),
      });
    });

    await page.goto("/admin?passkeyGen=success");
    await page.getByRole("button", { name: "Copy passkey" }).click();

    await expect(page.getByRole("status")).toContainText("Copy failed. Select and copy manually.");
    const fallbackAttempts = await page.evaluate(() => window.__copyFallbackAttempts);
    expect(fallbackAttempts).toBeGreaterThan(0);
  });

  test("renders production health and reminder controls", async ({ context, page }) => {
    await context.addCookies([
      {
        name: "admin_session",
        value: "test-admin-session",
        url: "http://127.0.0.1:3100",
      },
    ]);

    await page.goto("/admin");

    await expect(page.getByRole("heading", { name: "Production Health" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Preview Contacts" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Prepare Live Send" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Quick Guides" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Demo Recovery" })).toHaveCount(0);
  });
});

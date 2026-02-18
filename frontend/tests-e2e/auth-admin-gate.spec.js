const { test, expect } = require("@playwright/test");

test.describe("Admin Gate", () => {
  test("submits password and transitions to admin dashboard", async ({ page }) => {
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
    await page.getByRole("button", { name: "Enter Dashboard" }).click();

    await expect(page).toHaveURL(/\/admin$/);
    await expect(page.getByRole("heading", { name: "Admin Mock" })).toBeVisible();
    expect(postedPassword).toBe("super-secure-admin-password");
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

  test("shows one-time passkey flash without URL secret leakage", async ({ context, page }) => {
    await context.addCookies([
      {
        name: "admin_session",
        value: "test-admin-session",
        url: "http://127.0.0.1:3100",
      },
    ]);

    await page.route("**/api/admin/passkey-flash", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          creator_name: "Creator Prime",
          passkey: "flash-passkey-001",
        }),
      });
    });

    await page.goto("/admin?passkeyGen=success");
    await expect(page).toHaveURL(/\/admin\?passkeyGen=success$/);
    await expect(page).not.toHaveURL(/generatedPasskey=/);
    await expect(page.locator(".passkey-display")).toContainText("flash-passkey-001");
  });
});

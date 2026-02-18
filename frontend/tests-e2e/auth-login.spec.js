const { test, expect } = require("@playwright/test");

test.describe("Creator Login Flow", () => {
  test("completes lookup and confirm with trimmed passkey", async ({ page }) => {
    let lookupPasskey = null;
    let confirmPasskey = null;

    await page.route("**/api/auth/lookup", async (route) => {
      const body = JSON.parse(route.request().postData() || "{}");
      lookupPasskey = body.passkey;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          creator_id: "creator-001",
          creator_name: "Grace Bennett",
        }),
      });
    });

    await page.route("**/api/auth/confirm", async (route) => {
      const body = JSON.parse(route.request().postData() || "{}");
      confirmPasskey = body.passkey;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          creator_id: "creator-001",
          creator_name: "Grace Bennett",
        }),
      });
    });

    await page.route("**/portal", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "<html><body><h1>Portal Mock</h1></body></html>",
      });
    });

    await page.goto("/login");

    await expect(page.getByRole("heading", { name: "Sign In" })).toBeVisible();

    await page.getByLabel("Agency passkey").fill("  secure-passkey-001  ");
    await page.getByRole("button", { name: "Continue" }).click();

    await expect(page.getByRole("heading", { name: "Confirm Identity" })).toBeVisible();
    await expect(page.getByText("Grace Bennett")).toBeVisible();

    await page.getByRole("button", { name: /Yes, that.?s me/ }).click();
    await expect(page).toHaveURL(/\/portal$/);
    await expect(page.getByRole("heading", { name: "Portal Mock" })).toBeVisible();

    expect(lookupPasskey).toBe("secure-passkey-001");
    expect(confirmPasskey).toBe("secure-passkey-001");
  });

  test("shows API-provided error for invalid passkey", async ({ page }) => {
    await page.route("**/api/auth/lookup", async (route) => {
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({
          error: "Invalid passkey.",
          code: "INVALID_CREDENTIALS",
        }),
      });
    });

    await page.goto("/login");
    await page.getByLabel("Agency passkey").fill("wrong-passkey");
    await page.getByRole("button", { name: "Continue" }).click();

    await expect(page.locator("p.auth-feedback--error[role='alert']")).toContainText("Invalid passkey.");
    await expect(page.getByRole("heading", { name: "Sign In" })).toBeVisible();
  });

  test("lets user return to passkey step from confirmation", async ({ page }) => {
    await page.route("**/api/auth/lookup", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          creator_id: "creator-002",
          creator_name: "Alex Ryder",
        }),
      });
    });

    await page.goto("/login");
    await page.getByLabel("Agency passkey").fill("keep-this-key");
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByRole("heading", { name: "Confirm Identity" })).toBeVisible();

    await page.getByRole("button", { name: /This isn.?t me/ }).click();
    await expect(page.getByRole("heading", { name: "Sign In" })).toBeVisible();
    await expect(page.getByLabel("Agency passkey")).toHaveValue("");
  });
});

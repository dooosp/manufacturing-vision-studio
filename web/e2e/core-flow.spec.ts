import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";

const malformedPng = fileURLToPath(
  new URL("../../fixtures/adversarial/fake-signature.png", import.meta.url),
);

async function solidPng(page: Page, fill: string): Promise<Buffer> {
  const dataUrl = await page.evaluate((color) => {
    const canvas = document.createElement("canvas");
    canvas.width = 32;
    canvas.height = 24;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Canvas context is unavailable");
    context.fillStyle = color;
    context.fillRect(0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/png");
  }, fill);
  return Buffer.from(dataUrl.split(",", 2)[1] ?? "", "base64");
}

test.beforeEach(async ({ request }) => {
  const reset = await request.post("http://127.0.0.1:8000/api/demo/reset");
  expect(reset.ok(), await reset.text()).toBeTruthy();
});

test("engineer reviews deterministic evidence and exports a verified bundle", async ({
  page,
}, testInfo) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Manufacturing Vision Studio" })).toBeVisible();
  await expect(page.getByText("API connected", { exact: true })).toBeVisible();
  await expect(page.getByText("Synthetic evidence only.", { exact: false })).toBeVisible();

  const runInspection = page.getByRole("button", {
    name: /Run baseline inspection|Run again/,
  });
  await expect(runInspection).toBeEnabled();
  await runInspection.click();

  await expect(page.getByRole("button", { name: "Run again" })).toBeEnabled();
  await expect(page.getByText("ANOMALY", { exact: true })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "Anomaly overlay" })).toBeChecked();
  await expect(page.getByRole("radiogroup", { name: "Human disposition" })).toBeVisible();
  await expect(
    page.getByRole("img", { name: /Mask area of image pixels: .*Mask location:/ }),
  ).toBeVisible();

  await page.getByRole("radio", { name: "Needs review" }).focus();
  await page.keyboard.press("Space");
  await page.getByLabel("Reviewer").fill("Independent QA");
  await page.getByLabel("Decision note").fill(
    "Synthetic anomaly and lineage reviewed; field validation remains out of scope.",
  );
  await page.getByRole("button", { name: "Record disposition" }).focus();
  await page.keyboard.press("Enter");

  await expect(page.getByText("needs_review", { exact: true })).toBeVisible();
  const exportButton = page.getByRole("button", { name: "Export verified bundle" });
  await expect(exportButton).toBeEnabled();
  await exportButton.click();

  await expect(page.getByRole("status")).toContainText("Evidence bundle verified");
  await expect(page.getByRole("status")).toContainText("SHA-256");
  const screenshotPath = testInfo.outputPath("verified-evidence-workbench.png");
  await page.screenshot({ fullPage: true, path: screenshotPath });
  await testInfo.attach("verified-evidence-workbench", {
    path: screenshotPath,
    contentType: "image/png",
  });
  expect(pageErrors).toEqual([]);
});

test("English and Korean journeys preserve case identity and demo limitations", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("API connected", { exact: true })).toBeVisible();

  const workspaceIdentity = await page.locator("#workspace-title").textContent();
  expect(workspaceIdentity).toBeTruthy();

  await page.getByRole("button", { name: "한국어" }).focus();
  await page.keyboard.press("Enter");

  await expect(page.locator("html")).toHaveAttribute("lang", "ko");
  await expect(page.getByText("API 연결됨", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "증거 무결성" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "사람 최종 판정" })).toBeVisible();
  await expect(page.getByText("합성 증거 전용입니다.", { exact: false })).toBeVisible();
  await expect(page.locator("#workspace-title")).toHaveText(workspaceIdentity ?? "");
  await expect(page.getByRole("button", { name: /기준 검사 실행|다시 실행/ })).toBeVisible();
  await expect(page.getByRole("radio", { name: "승인" })).toBeVisible();
  await expect(page.getByRole("radio", { name: "반려" })).toBeVisible();
  await expect(page.getByRole("radio", { name: "추가 검토" })).toBeVisible();
  await expect(page.getByRole("radio", { name: "모델 오류" })).toBeVisible();

  await page.setViewportSize({ width: 640, height: 900 });
  await expect(page.getByRole("heading", { name: "증거 무결성" })).toBeVisible();
  await expect(page.getByText("생산, 안전, 작업장 출하 검증을 주장하지 않습니다.", {
    exact: false,
  })).toBeVisible();
  const viewport = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(viewport.scrollWidth).toBeLessThanOrEqual(viewport.clientWidth);
});

test("displayed image and evidence hash follow the analyzed inspection binding", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByText("API connected", { exact: true })).toBeVisible();

  const reference = await solidPng(page, "rgb(30, 60, 90)");
  const firstInspection = await solidPng(page, "rgb(35, 60, 90)");
  const secondInspection = await solidPng(page, "rgb(220, 180, 40)");
  const secondHash = createHash("sha256").update(secondInspection).digest("hex");

  await page.getByRole("button", { name: "New case" }).click();
  await page.getByLabel("Part ID").fill("PART-MULTI-IMAGE");
  await page.getByLabel("Revision").fill("REV-B");
  await page.getByRole("button", { name: "Create case" }).click();
  await expect(page.locator("#workspace-title")).toHaveText("PART-MULTI-IMAGE");

  const uploadReference = page.getByLabel("Upload reference");
  await uploadReference.focus();
  await expect(uploadReference).toBeFocused();
  await expect(uploadReference.locator("..")).toHaveCSS("outline-style", "solid");
  const fileChooserPromise = page.waitForEvent("filechooser");
  await page.keyboard.press("Enter");
  const fileChooser = await fileChooserPromise;
  await fileChooser.setFiles({
    name: "reference-binding.png",
    mimeType: "image/png",
    buffer: reference,
  });
  await expect(page.locator(".case-id")).toContainText("State rev 2");

  const uploadInspection = page.getByLabel("Upload inspection");
  await uploadInspection.setInputFiles({
    name: "inspection-first.png",
    mimeType: "image/png",
    buffer: firstInspection,
  });
  await expect(page.locator(".case-id")).toContainText("State rev 3");
  await uploadInspection.setInputFiles({
    name: "inspection-second.png",
    mimeType: "image/png",
    buffer: secondInspection,
  });
  await expect(page.locator(".case-id")).toContainText("State rev 4");

  await page.getByRole("button", { name: "Run baseline inspection" }).click();
  await expect(page.getByRole("button", { name: "Run again" })).toBeEnabled();
  await expect(page.getByText("inspection-second.png", { exact: true })).toBeVisible();
  await expect(
    page
      .getByRole("region", { name: "Evidence integrity" })
      .getByText(secondHash, { exact: true }),
  ).toBeVisible();
});

test("malformed upload is surfaced as a safe failure and cannot enable analysis", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByText("API connected", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "New case" }).click();
  await page.getByLabel("Part ID").fill("PART-FAIL-CLOSED");
  await page.getByLabel("Revision").fill("REV-A");
  await page.getByRole("button", { name: "Create case" }).click();
  await expect(page.locator("#workspace-title")).toHaveText("PART-FAIL-CLOSED");

  await page.getByLabel("Upload reference").setInputFiles(malformedPng);

  const alert = page.getByRole("alert");
  await expect(alert).toContainText("The operation stopped safely");
  await expect(alert).toContainText("[IMAGE_DECODE_FAILED]");
  await expect(alert).not.toContainText("Traceback");
  await expect(alert).not.toContainText("/Users/");
  await expect(page.getByRole("button", { name: "Run baseline inspection" })).toBeDisabled();
  await expect(page.locator("#workspace-title")).toHaveText("PART-FAIL-CLOSED");
  await expect(
    page.getByRole("region", { name: "PART-FAIL-CLOSED", exact: true }).getByText("Draft"),
  ).toBeVisible();
});

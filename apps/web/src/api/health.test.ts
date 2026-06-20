import { describe, expect, it } from "vitest";

import { healthStatusText } from "./health";

describe("healthStatusText", () => {
  it("maps health states to user-facing labels", () => {
    expect(healthStatusText("ok")).toBe("服务可用");
    expect(healthStatusText("degraded")).toBe("部分检查未通过");
    expect(healthStatusText("error")).toBe("无法连接后端");
    expect(healthStatusText("unknown")).toBe("等待检查");
  });
});

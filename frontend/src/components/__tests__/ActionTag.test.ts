import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import ActionTag from "../ActionTag.vue";

describe("ActionTag", () => {
  it("maps BUY -> green, SELL -> red, HOLD -> blue", () => {
    const buy = mount(ActionTag, { props: { value: "BUY" } });
    expect(buy.attributes("color") ?? buy.html()).toContain("green");

    const sell = mount(ActionTag, { props: { value: "SELL" } });
    expect(sell.html()).toContain("red");

    const hold = mount(ActionTag, { props: { value: "HOLD" } });
    expect(hold.html()).toContain("blue");
  });

  it("renders the value text", () => {
    const w = mount(ActionTag, { props: { value: "BUY" } });
    expect(w.text()).toBe("BUY");
  });
});

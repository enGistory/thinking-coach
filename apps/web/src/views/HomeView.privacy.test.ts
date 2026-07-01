import { describe, expect, it } from "vitest";

import homeViewSource from "./HomeView.vue?raw";

describe("HomeView privacy controls", () => {
  it("does not render deletion proof lookup as a normal saved text field", () => {
    const proofInputMatch = homeViewSource.match(
      /<input\s+v-model="deletionStatusProof"[\s\S]*?>/,
    );

    expect(proofInputMatch?.[0]).toContain('type="password"');
    expect(proofInputMatch?.[0]).toContain('autocomplete="off"');
    expect(proofInputMatch?.[0]).toContain('spellcheck="false"');
  });

  it("clears local pending audio after destructive deletion requests succeed", () => {
    const deleteTrainingBlock = homeViewSource.match(/async function deleteCurrentTraining\(\) \{[\s\S]*?\n\}/);
    const deleteAccountBlock = homeViewSource.match(/async function requestAccountDeletion\(\) \{[\s\S]*?\n\}/);

    expect(deleteTrainingBlock?.[0]).toContain("await forgetAllPendingAudio();");
    expect(deleteAccountBlock?.[0]).toContain("await forgetAllPendingAudio();");
    expect(homeViewSource).toContain("async function forgetAllPendingAudio()");
    expect(homeViewSource).toContain("await clearPendingAudioBestEffort();");
  });
});

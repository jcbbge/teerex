const std = @import("std");

// Compiled collection allowlist. CI rejects declared flags absent here.
pub const names = " accept-omissions ack-timeout-ms adapter after all allow-attached-viewers allow-experimental allow-sensitive-capture allow-sensitive-storage anchor answer app apply archive args arguments ask autostart baseline before behaviour block board-store bounds brief-file by callback-config callback-host caller card-file catalog channel-dir check checkpoint-every-bytes cleanup color columns command-json config confirm context create-session cwd deactivate deadline-unix-ms definition detach detail direction directory draft draft-wait-ms env-file event-file event-id expect extension facts file fixture focus for-days from from-owner gap-s generation handle harness help host hosts id init interval-ms jobs-registry json keep-open kind label launch-id launch-wait-ms layout library limit list log-dir map-file max-bytes message-file metadata min-episodes name no-deadline no-extensions observation observations-out once operation option out output-dir owner pace pane path payload plan policy print-config print-view profile profiles protect-file publish-receipt-file purpose ratio reason receipt-file recommend record-identities record-out registry relocate report-to-block report-to-session request-id resolve review-at rex root routed rows sample scene scope script server session settings since snapshot socket starter-block starter-session startup-ms state status-id status-state stdin-file store tail targets-file teerex term-json then timeout timeout-ms title to token tool ttl-seconds tty version view view-rules wait-ms wait-ms0 width window workdir yes ";

pub fn allowed(name: []const u8) bool {
    var words = std.mem.tokenizeScalar(u8, names, ' ');
    while (words.next()) |word| if (std.mem.eql(u8, name, word)) return true;
    return false;
}

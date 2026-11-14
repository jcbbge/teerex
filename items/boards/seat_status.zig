// The Python source boards and send embed; shared with the send cartridge.
pub const seat_status_source = @embedFile("attention.py") ++ "\n" ++ @embedFile("seat_status.py");

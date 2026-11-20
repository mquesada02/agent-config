#[test]
fn sums_a_long_range() {
    let total: u64 = (0..400_000_000u64).map(std::hint::black_box).sum();
    assert_eq!(total, 79_999_999_800_000_000);
}

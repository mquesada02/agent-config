#[test]
fn reads_the_mode_set_by_the_test() {
    std::env::set_var("DEMO_MODE", "fast");
    assert_eq!(demo::mode(), "fast");
}

#[test]
fn defaults_the_mode() {
    assert_eq!(demo::mode(), "slow");
}

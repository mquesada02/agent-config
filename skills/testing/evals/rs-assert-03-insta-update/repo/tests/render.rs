#[test]
fn renders_a_report() {
    let report = demo::render();
    insta::assert_snapshot!(report);
}

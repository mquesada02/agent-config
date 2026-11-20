use demo::text::shout;

#[test]
fn shouts_a_word() {
    assert_eq!(shout("hi"), "HI!");
}

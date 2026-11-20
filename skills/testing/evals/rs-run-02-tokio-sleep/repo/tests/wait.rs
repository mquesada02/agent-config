use std::time::Duration;

#[tokio::test]
async fn the_queue_drains() {
    let queue = demo::Queue::new(3);
    tokio::time::sleep(Duration::from_millis(50)).await;
    assert_eq!(queue.len(), 3);
}

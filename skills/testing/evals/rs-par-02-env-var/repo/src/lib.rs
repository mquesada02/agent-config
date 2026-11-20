pub fn mode() -> String {
    std::env::var("DEMO_MODE").unwrap_or_else(|_| "slow".to_string())
}

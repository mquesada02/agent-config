/// Upper-cases the word and adds an exclamation mark.
pub fn shout(word: &str) -> String {
    format!("{}!", word.to_uppercase())
}

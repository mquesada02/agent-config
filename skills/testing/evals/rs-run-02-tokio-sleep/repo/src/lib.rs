pub struct Queue {
    items: usize,
}

impl Queue {
    pub fn new(items: usize) -> Queue {
        Queue { items }
    }

    pub fn len(&self) -> usize {
        self.items
    }
}

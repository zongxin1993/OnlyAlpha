use crate::application::job_input::{InputError, MemoryBudget};

#[test]
fn declared_memory_is_checked_before_allocation_and_never_wraps() {
    let budget = MemoryBudget::new(10, 4096).unwrap();
    assert_eq!(budget.check(11, 1), Err(InputError::BudgetExceeded));
    assert_eq!(budget.check(1, 4097), Err(InputError::BudgetExceeded));
    assert_eq!(budget.check(10, 4096), Ok(()));
    assert_eq!(
        budget.check(u64::MAX, usize::MAX),
        Err(InputError::BudgetExceeded)
    );
    assert!(MemoryBudget::new(0, 1).is_err());
    assert!(MemoryBudget::new(1, 0).is_err());
    assert!(MemoryBudget::new(1_000_001, 1024).is_err());
    assert!(MemoryBudget::new(1, 128 * 1024 * 1024 + 1).is_err());
}

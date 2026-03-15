document.addEventListener('DOMContentLoaded', () => {
    const showSemesterBtn = document.getElementById('showSemesterBtn');
    const semesterGroup = document.getElementById('semesterGroup');
    const semesterInput = document.getElementById('semester');

    if (!showSemesterBtn || !semesterGroup) {
        return;
    }

    showSemesterBtn.addEventListener('click', () => {
        semesterGroup.classList.remove('d-none');
        showSemesterBtn.classList.add('d-none');
        if (semesterInput) {
            semesterInput.focus();
        }
    });
});

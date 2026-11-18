
const searchInput = document.getElementById("visitorSearch");
const visitorTable = document.getElementById("visitorTable");

if (searchInput && visitorTable) {
    searchInput.addEventListener("input", function () {
        const search = this.value.toLowerCase();

        const rows = visitorTable.querySelectorAll("tbody tr");

        rows.forEach(row => {
            const matches = row.textContent.toLowerCase().includes(search);
            row.style.display = matches ? "" : "none";
        });
    });
}

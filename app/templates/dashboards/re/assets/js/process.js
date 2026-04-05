document.addEventListener("DOMContentLoaded", () => {
  // Toggle Sidebar
  function toggleSidebar() {
    const sidebar = document.getElementById("sidebar");
    const menuIcon = document.querySelector(".menu-icon i");

    if (!sidebar || !menuIcon) return;

    sidebar.classList.toggle("open");

    if (menuIcon.classList.contains("bx-menu")) {
      menuIcon.classList.replace("bx-menu", "bx-x");
    } else {
      menuIcon.classList.replace("bx-x", "bx-menu");
    }
  }

  // Close sidebar when clicking outside
  function closeSidebarIfClickedOutside(event) {
    const sidebar = document.getElementById("sidebar");
    const menuIcon = document.querySelector(".menu-icon i");

    if (!sidebar || !menuIcon) return;

    if (!sidebar.contains(event.target) && !menuIcon.contains(event.target)) {
      sidebar.classList.remove("open");
      menuIcon.classList.replace("bx-x", "bx-menu");
    }
  }

  document.addEventListener("click", closeSidebarIfClickedOutside);

  // Toggle Submenu
  function toggleSubmenu(event) {
    event.preventDefault();

    let parent = event.target.closest(".submenu");
    if (!parent) return;

    let submenu = parent.querySelector(".submenu-items");
    if (!submenu) return;

    // Close other submenus
    document.querySelectorAll(".submenu-items").forEach((item) => {
      if (item !== submenu) {
        item.classList.remove("open");
        item.style.display = "none";
        item.parentElement.classList.remove("open");
      }
    });

    if (submenu.classList.contains("open")) {
      submenu.classList.remove("open");
      submenu.style.display = "none";
      parent.classList.remove("open");
    } else {
      submenu.classList.add("open");
      submenu.style.display = "block";
      parent.classList.add("open");
    }
  }

  // Search and Pagination
  const searchInput = document.getElementById('searchInput');
  const entriesSelect = document.getElementById('entriesSelect');
  const table = document.getElementById('guidelinesTable');
  const rows = table ? Array.from(table.querySelectorAll('tbody tr')) : [];
  const pagination = document.getElementById('pagination');

  let currentPage = 1;
  let entriesPerPage = parseInt(entriesSelect?.value) || 10;

  function renderTable() {
    if (!table || rows.length === 0) return;

    const start = (currentPage - 1) * entriesPerPage;
    const end = start + entriesPerPage;

    rows.forEach((row, index) => {
      row.style.display = index >= start && index < end ? '' : 'none';
    });

    renderPagination();
  }

  function renderPagination() {
    if (!pagination || rows.length === 0) return;

    pagination.innerHTML = '';
    const totalPages = Math.ceil(rows.length / entriesPerPage);

    for (let i = 1; i <= totalPages; i++) {
      const btn = document.createElement('button');
      btn.textContent = i;
      btn.className = i === currentPage ? 'active' : '';
      btn.addEventListener('click', () => {
        currentPage = i;
        renderTable();
      });
      pagination.appendChild(btn);
    }
  }

  if (searchInput) {
    searchInput.addEventListener('input', () => {
      const filter = searchInput.value.toLowerCase();
      rows.forEach(row => {
        row.style.display = row.textContent.toLowerCase().includes(filter) ? '' : 'none';
      });
    });
  }

  if (entriesSelect) {
    entriesSelect.addEventListener('change', () => {
      entriesPerPage = parseInt(entriesSelect.value);
      currentPage = 1;
      renderTable();
    });
  }

  // Toggle Dropdown
  function toggleDropdown(event, element) {
    event.stopPropagation(); // Fix event propagation issue

    const dropdown = element.nextElementSibling;

    document.querySelectorAll(".dropdown-content").forEach((item) => {
      if (item !== dropdown) {
        item.style.display = "none";
      }
    });

    dropdown.style.display = dropdown.style.display === "block" ? "none" : "block";
  }

  // Close dropdown when clicking outside
  window.addEventListener("click", () => {
    document.querySelectorAll(".dropdown-content").forEach((dropdown) => {
      dropdown.style.display = "none";
    });
  });

  // Export to CSV
  function exportRowToCSV(element) {
    const row = element.closest('tr');
    if (!row) return;

    const cells = Array.from(row.querySelectorAll('td')).map(cell => cell.innerText);
    const csvContent = cells.join(',') + '\n';

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'guideline_row.csv';
    link.click();
  }

  // Initial render
  renderTable();
});

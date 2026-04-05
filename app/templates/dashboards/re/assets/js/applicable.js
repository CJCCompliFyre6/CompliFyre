// Toggle Sidebar
function toggleSidebar() {
    document.getElementById("sidebar").classList.toggle("open");
    const menuIcon = document.querySelector(".menu-icon i"); // Get the current icon

    // Toggle the icon when the sidebar opens or closes
    if (menuIcon.classList.contains("bx-menu")) {
        menuIcon.classList.replace("bx-menu", "bx-x"); // Switch to close icon
    } else {
        menuIcon.classList.replace("bx-x", "bx-menu"); // Switch back to menu icon
    }
}

// Function to close the sidebar when clicking outside
function closeSidebarIfClickedOutside(event) {
    const sidebar = document.getElementById("sidebar");
    const menuIcon = document.querySelector(".menu-icon i");
    
    // Check if the click is outside the sidebar and not on the menu icon
    if (!sidebar.contains(event.target) && !menuIcon.contains(event.target)) {
        sidebar.classList.remove("open");
        menuIcon.classList.replace("bx-x", "bx-menu"); // Revert the icon back to the menu
    }
}

// Add the event listener to close sidebar if clicking outside
document.addEventListener("click", closeSidebarIfClickedOutside);


function toggleSubmenu(event) {
  event.preventDefault(); // Prevents page reload

  let parent = event.target.closest(".submenu"); // Find the clicked <li>
  let submenu = parent.querySelector(".submenu-items"); // Find submenu in this <li>

  // Close all other submenus before opening the clicked one
  document.querySelectorAll(".submenu-items").forEach((item) => {
    if (item !== submenu) {
      item.classList.remove("open"); // Use class to control the display
      item.style.display = "none"; // Remove inline style if necessary
      item.parentElement.classList.remove("open");
    }
  });

  // Toggle the clicked submenu
  if (submenu.classList.contains("open")) {
    submenu.classList.remove("open");
    submenu.style.display = "none"; // Close
    parent.classList.remove("open");
  } else {
    submenu.classList.add("open");
    submenu.style.display = "block"; // Open
    parent.classList.add("open");
  }
}

// Tabbed Content
function showContent(index) {
    document.querySelectorAll(".tab").forEach((tab, i) => {
        tab.classList.toggle("active", i === index);
    });
    
    document.querySelectorAll(".content").forEach((content, i) => {
        content.classList.toggle("active", i === index);
    });
}


let currentPage = 1;
let rowsPerPage = 5;

function changeEntries() {
  rowsPerPage = parseInt(document.getElementById("entriesSelect").value);
  currentPage = 1; // Reset to page 1 when entries change
  renderTable('regulations');
}

function renderTable(tableId) {
  const table = document.getElementById(tableId);
  const rows = table.querySelectorAll('tbody tr');
  const totalRows = rows.length;
  const totalPages = Math.ceil(totalRows / rowsPerPage);

  // Hide all rows first
  rows.forEach(row => row.style.display = 'none');

  // Display rows for the current page
  const startIndex = (currentPage - 1) * rowsPerPage;
  const endIndex = startIndex + rowsPerPage;
  for (let i = startIndex; i < endIndex && i < totalRows; i++) {
    rows[i].style.display = 'table-row';
  }

  // Render Pagination
  renderPagination(totalPages);
}

function renderPagination(totalPages) {
  const pagination = document.getElementById("pagination");
  pagination.innerHTML = '';

  for (let i = 1; i <= totalPages; i++) {
    const pageButton = document.createElement("button");
    pageButton.textContent = i;
    pageButton.onclick = () => {
      currentPage = i;
      renderTable('regulations');
    };
    pagination.appendChild(pageButton);
  }
}

function searchTable(tableId) {
  const searchTerm = document.getElementById(`search-${tableId}`).value.toLowerCase();
  const rows = document.querySelectorAll(`#table-body-${tableId} tr`);

  rows.forEach(row => {
    const columns = row.querySelectorAll('td');
    let match = false;

    columns.forEach(column => {
      if (column.innerText.toLowerCase().includes(searchTerm)) {
        match = true;
      }
    });

    row.style.display = match ? '' : 'none';
  });
}

function exportToCSV(tableId) {
  const table = document.getElementById(tableId);
  let csvContent = '';

  // Add headers
  const headers = Array.from(table.querySelectorAll("thead th")).map(header => header.innerText);
  csvContent += headers.join(",") + "\n";

  // Add table rows
  const rows = table.querySelectorAll("tbody tr");
  rows.forEach(row => {
    const cells = Array.from(row.querySelectorAll("td")).map(cell => cell.innerText);
    csvContent += cells.join(",") + "\n";
  });

  // Create a download link
  const link = document.createElement("a");
  link.href = 'data:text/csv;charset=utf-8,' + encodeURI(csvContent);
  link.target = '_blank';
  link.download = tableId + '.csv';
  link.click();
}

// Initialize table on page load
document.addEventListener("DOMContentLoaded", function() {
  renderTable('regulations');
});

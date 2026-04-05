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

// Tab Switching
const tabs = document.querySelectorAll('.tabs button');
const tabContents = document.querySelectorAll('.tab-content');

tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => {
    // Remove 'active' class from all tabs
    tabs.forEach(tab => tab.classList.remove('active'));
    // Add 'active' class to the clicked tab
    tab.classList.add('active');

    // Hide all tab contents
    tabContents.forEach(content => content.classList.remove('active'));
    // Show the corresponding tab content
    tabContents[index].classList.add('active');
  });
});

// Pagination and entry management
let currentPageCyberSec = 1;
let rowsPerPageCyberSec = 10;

let currentPageIrac = 1;
let rowsPerPageIrac = 10;

const cyberSecTable = document.getElementById('cybersec').querySelector('table');
const iracTable = document.getElementById('irac').querySelector('table');

const cyberSecPagination = document.getElementById('cybersec-pagination');
const iracPagination = document.getElementById('irac-pagination');

const cyberSecEntriesSelector = document.getElementById('cybersec-entries');
const iracEntriesSelector = document.getElementById('irac-entries');

function updateTableCyberSec() {
    rowsPerPageCyberSec = parseInt(cyberSecEntriesSelector.value);
    currentPageCyberSec = 1;  // Reset to the first page
    displayRowsCyberSec();
}

function updateTableIrac() {
    rowsPerPageIrac = parseInt(iracEntriesSelector.value);
    currentPageIrac = 1;  // Reset to the first page
    displayRowsIrac();
}

function displayRowsCyberSec() {
    const rows = cyberSecTable.querySelectorAll('tbody tr');
    const totalRows = rows.length;
    const totalPages = Math.ceil(totalRows / rowsPerPageCyberSec);

    // Hide all rows
    rows.forEach(row => row.style.display = 'none');

    // Show rows for the current page
    const start = (currentPageCyberSec - 1) * rowsPerPageCyberSec;
    const end = currentPageCyberSec * rowsPerPageCyberSec;

    for (let i = start; i < end && i < totalRows; i++) {
        rows[i].style.display = '';
    }

    // Update pagination buttons
    createPaginationButtons(cyberSecPagination, totalPages, 'cyberSec');
}

function displayRowsIrac() {
    const rows = iracTable.querySelectorAll('tbody tr');
    const totalRows = rows.length;
    const totalPages = Math.ceil(totalRows / rowsPerPageIrac);

    // Hide all rows
    rows.forEach(row => row.style.display = 'none');

    // Show rows for the current page
    const start = (currentPageIrac - 1) * rowsPerPageIrac;
    const end = currentPageIrac * rowsPerPageIrac;

    for (let i = start; i < end && i < totalRows; i++) {
        rows[i].style.display = '';
    }

    // Update pagination buttons
    createPaginationButtons(iracPagination, totalPages, 'irac');
}

function createPaginationButtons(paginationElement, totalPages, tab) {
    paginationElement.innerHTML = '';  // Clear existing buttons

    for (let i = 1; i <= totalPages; i++) {
        const button = document.createElement('button');
        button.textContent = i;
        button.onclick = () => {
            if (tab === 'cyberSec') {
                currentPageCyberSec = i;
                displayRowsCyberSec();
            } else {
                currentPageIrac = i;
                displayRowsIrac();
            }
        };
        paginationElement.appendChild(button);
    }
}

// Initialize both tables on page load
displayRowsCyberSec();
displayRowsIrac();

// Debounced Search Function
function debounce(fn, delay) {
    let timeout;
    return function () {
        clearTimeout(timeout);
        timeout = setTimeout(fn, delay);
    };
}

document.getElementById('search').addEventListener('input', debounce(function() {
    searchTable('cybersec-table', 'search');
}, 300));

document.getElementById('search-irac').addEventListener('input', debounce(function() {
    searchTable('irac-table', 'search-irac');
}, 300));

function searchTable(tableId, searchId) {
    var filter = document.getElementById(searchId).value.toLowerCase();
    var rows = document.getElementById(tableId).getElementsByTagName('tr');

    for (var i = 1; i < rows.length; i++) {
        var cells = rows[i].getElementsByTagName('td');
        var found = false;

        for (var j = 0; j < cells.length; j++) {
            if (cells[j].textContent.toLowerCase().indexOf(filter) > -1) {
                found = true;
                break;
            }
        }

        rows[i].style.display = found ? '' : 'none';
    }
}

// Export Table to CSV
function exportTableToCSV(filename) {
    var table = document.getElementById(filename.includes('cybersec') ? 'cybersec-table' : 'irac-table');
    var rows = table.querySelectorAll('tr');
    var csv = [];

    for (var i = 0; i < rows.length; i++) {
        var row = rows[i];
        var cols = row.querySelectorAll('td, th');
        var data = [];

        for (var j = 0; j < cols.length; j++) {
            data.push('"' + cols[j].textContent.trim().replace(/"/g, '""') + '"');
        }

        csv.push(data.join(','));
    }

    var csvFile = new Blob([csv.join('\n')], { type: 'text/csv' });
    var link = document.createElement('a');
    link.href = URL.createObjectURL(csvFile);
    link.download = filename;
    link.click();
}

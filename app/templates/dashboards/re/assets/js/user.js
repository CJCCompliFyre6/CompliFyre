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

// search//
function search() {
    var input, filter, table, tr, td, i, txtValue;
    input = document.getElementById("search");
    filter = input.value.toUpperCase();
    table = document.querySelector("table");
    tr = table.getElementsByTagName("tr");

    for (i = 1; i < tr.length; i++) {
      td = tr[i].getElementsByTagName("td");
      let found = false;
      
      for (let j = 0; j < td.length; j++) {
        if (td[j]) {
          txtValue = td[j].textContent || td[j].innerText;
          if (txtValue.toUpperCase().indexOf(filter) > -1) {
            found = true;
            break;
          }
        }
      }

      if (found) {
        tr[i].style.display = "";
      } else {
        tr[i].style.display = "none";
      }
    }
  }



  //   export     //
  // Function to export table data to CSV
function exportToCSV() {
    // Get all rows from the table
    const rows = document.querySelectorAll("table tbody tr");
    
    // Create an array to hold the data
    const csvData = [];
  
    // Loop through each row
    rows.forEach(row => {
      // Get all columns in the row
      const cols = row.querySelectorAll("td");
      
      // Extract text content of each column and push it into the csvData array
      const rowData = [];
      cols.forEach(col => {
        rowData.push(col.textContent.trim());
      });
      
      // Add the row data to the csvData array
      csvData.push(rowData.join(","));
    });
  
    // Convert the csvData array to a string
    const csvString = csvData.join("\n");
  
    // Create a link element
    const link = document.createElement("a");
    
    // Set the download attribute with a file name
    link.setAttribute("download", "user_list.csv");
    
    // Create a Blob from the CSV string and create an object URL for the link
    const blob = new Blob([csvString], { type: "text/csv" });
    link.href = URL.createObjectURL(blob);
    
    // Trigger the download by simulating a click
    link.click();
  }

  

  //     entries box     //
  // Function to handle the change in entries box
document.getElementById('entries').addEventListener('change', function() {
    const entries = parseInt(this.value);
    const tableRows = document.querySelectorAll('#userTableBody tr');
    const totalRows = tableRows.length;

    // Hide or show rows based on selected entries
    for (let i = 0; i < totalRows; i++) {
        if (i < entries) {
            tableRows[i].style.display = ''; // Show row
        } else {
            tableRows[i].style.display = 'none'; // Hide row
        }
    }

    // Reset the pagination to start from the first page
    document.getElementById('pageNumber').textContent = '1';
});

// Function for handling pagination (for next and previous buttons)
let currentPage = 1;

document.getElementById('next').addEventListener('click', function() {
    const entries = parseInt(document.getElementById('entries').value);
    const tableRows = document.querySelectorAll('#userTableBody tr');
    const totalRows = tableRows.length;
    const totalPages = Math.ceil(totalRows / entries);

    if (currentPage < totalPages) {
        currentPage++;
        updateTable();
    }
});

document.getElementById('prev').addEventListener('click', function() {
    if (currentPage > 1) {
        currentPage--;
        updateTable();
    }
});

// Function to update the table display based on the current page and entries per page
function updateTable() {
    const entries = parseInt(document.getElementById('entries').value);
    const tableRows = document.querySelectorAll('#userTableBody tr');
    const totalRows = tableRows.length;

    const startRow = (currentPage - 1) * entries;
    const endRow = startRow + entries;

    for (let i = 0; i < totalRows; i++) {
        if (i >= startRow && i < endRow) {
            tableRows[i].style.display = ''; // Show row
        } else {
            tableRows[i].style.display = 'none'; // Hide row
        }
    }

    document.getElementById('pageNumber').textContent = currentPage;
}

// Initialize the table when the page loads
window.addEventListener('load', function() {
    updateTable();
});


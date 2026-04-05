// Toggle Sidebar
function toggleSidebar() {
    document.getElementById("sidebar").classList.toggle("open");
    const menuIcon = document.querySelector(".menu-icon i");
  
    if (menuIcon.classList.contains("bx-menu")) {
        menuIcon.classList.replace("bx-menu", "bx-x");
    } else {
        menuIcon.classList.replace("bx-x", "bx-menu");
    }
  }
  
  // Function to close the sidebar when clicking outside
  function closeSidebarIfClickedOutside(event) {
    const sidebar = document.getElementById("sidebar");
    const menuIcon = document.querySelector(".menu-icon i");
    
    if (!sidebar.contains(event.target) && !menuIcon.contains(event.target)) {
        sidebar.classList.remove("open");
        menuIcon.classList.replace("bx-x", "bx-menu");
    }
  }

  
  
// function openUploadModal() {
//   const modal = document.getElementById("uploadModal");
//   modal.classList.remove("hidden");
//   modal.classList.add("flex");
// }

// function closeUploadModal() {
//   const modal = document.getElementById("uploadModal");
//   modal.classList.remove("flex");
//   modal.classList.add("hidden");
// }


  // Add the event listener to close sidebar if clicking outside
  document.addEventListener("click", closeSidebarIfClickedOutside);
  
  function toggleSubmenu(event) {
    event.preventDefault();
  
    let parent = event.target.closest(".submenu");
    let submenu = parent.querySelector(".submenu-items");
  
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

  function toggleSubmenu(event) {
    event.preventDefault();
    const submenu = event.target.nextElementSibling;
    if (submenu) {
      submenu.classList.toggle('active');
    }
  }
  
  const searchInput = document.getElementById('searchInput');
  const entriesSelect = document.getElementById('entriesSelect');
  const table = document.getElementById('guidelinesTable');
  const rows = Array.from(table.querySelectorAll('tbody tr'));
  const pagination = document.getElementById('pagination');
  
  let currentPage = 1;
  let entriesPerPage = parseInt(entriesSelect.value);
  
  function renderTable() {
    const start = (currentPage - 1) * entriesPerPage;
    const end = start + entriesPerPage;
  
    rows.forEach((row, index) => {
        row.style.display = (index >= start && index < end) ? '' : 'none';
    });
  
    renderPagination();
  }
  
  function renderPagination() {
    pagination.innerHTML = '';
    const totalPages = Math.ceil(rows.length / entriesPerPage);
  
    for (let i = 1; i <= totalPages; i++) {
        const btn = document.createElement('button');
        btn.textContent = i;
        btn.className = (i === currentPage) ? 'active' : '';
        btn.addEventListener('click', () => {
            currentPage = i;
            renderTable();
        });
        pagination.appendChild(btn);
    }
  }
  
  // Fix event handling for dropdown
  function toggleDropdown(event) {
    event.stopPropagation(); // Stop the click event from propagating
  
    const dropdown = event.target.nextElementSibling; // Get the dropdown menu next to the clicked span
  
    // Close other dropdowns before opening the clicked one
    document.querySelectorAll(".dropdown-content").forEach((item) => {
        if (item !== dropdown) item.classList.remove('show');
    });
  
    dropdown.classList.toggle('show');
  }
  
  // Close dropdown when clicking outside
  document.addEventListener('click', function (event) {
    if (!event.target.closest('.dropdown')) {
        document.querySelectorAll(".dropdown-content").forEach((dropdown) => {
            dropdown.classList.remove('show');
        });
    }
  });
  
  searchInput.addEventListener('input', () => {
    const filter = searchInput.value.toLowerCase();
    rows.forEach(row => {
        row.style.display = row.textContent.toLowerCase().includes(filter) ? '' : 'none';
    });
  });
  
  entriesSelect.addEventListener('change', () => {
    entriesPerPage = parseInt(entriesSelect.value);
    currentPage = 1;
    renderTable();
  });
  
  
  document.getElementById('exportCSV').addEventListener('click', function() {
    // Get the table
    var table = document.getElementById('guidelinesTable');
  
    // Initialize the CSV content
    var csvContent = "data:text/csv;charset=utf-8,";
    
    // Loop through table rows and columns to extract data
    for (var i = 0; i < table.rows.length; i++) {
        var row = table.rows[i];
        var rowData = [];
  
        for (var j = 0; j < row.cells.length - 1; j++) {  // excluding the last column (Action column)
            rowData.push('"' + row.cells[j].innerText + '"');  // Add quotes around cell data
        }
  
        csvContent += rowData.join(",") + "\n"; // Join the row data with commas and add a newline
    }
  
    // Create a link element to trigger the download
    var encodedUri = encodeURI(csvContent);
    var link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", "guidelines.csv");
  
    // Trigger the download by simulating a click event
    link.click();
  });
  
  
  function uploadFile() {
      let fileInput = document.getElementById("fileInput");
      let file = fileInput.files[0]; // Get the first selected file
  
      if (file) {
          document.getElementById("fileName").innerText = "Selected file: " + file.name;
  
          // If sending to a server:
          let formData = new FormData();
          formData.append("file", file);
  
          fetch("/upload-endpoint", {
              method: "POST",
              body: formData
          }).then(response => response.json())
            .then(data => alert("File uploaded successfully!"))
            .catch(error => alert("Error uploading file."));
      } else {
          alert("Please select a file first!");
      }
      
  }
  
  
  renderTable();
  
  
  
  // Function to toggle the visibility of the dropdown content
  function toggleDropdown2(element) {
    const dropdownContent = element.closest('.action-menu').querySelector('.dropdown-content2');
    dropdownContent.classList.toggle('show'); // Toggle the 'show' class to display or hide the dropdown
  }
  
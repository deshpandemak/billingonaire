<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { auth } from '$lib/firebase';
  import { onAuthStateChanged } from 'firebase/auth';

  let data = [];
  let searchCriteria = {
    startDate: '',
    endDate: '',
    advocateName: '',
    caseNumber: ''
  };

  const fetchData = async () => {
    if (!searchCriteria.startDate && !searchCriteria.endDate && !searchCriteria.advocateName && !searchCriteria.caseNumber) {
      alert('Please fill at least one search criteria');
      return;
    }

    try {
      const response = await fetch('http://localhost:8000/get-data', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(searchCriteria)
      });
      if (!response.ok) {
        throw new Error('Failed to fetch data');
      }
      data = await response.json();
    } catch (e) {
      console.error(e);
    }
  };

  const filterData = () => {
    return data.filter(item => {
      const itemDate = new Date(item.Date);
      const startDate = new Date(searchCriteria.startDate);
      const endDate = new Date(searchCriteria.endDate);
      const advocateName = searchCriteria.advocateName.toLowerCase();
      const caseNumber = searchCriteria.caseNumber.toLowerCase();

      return (
        (!searchCriteria.startDate || itemDate >= startDate) &&
        (!searchCriteria.endDate || itemDate <= endDate) &&
        (!searchCriteria.advocateName || item['Advocate Name'].toLowerCase().includes(advocateName)) &&
        (!searchCriteria.caseNumber || item['Case Number'].toLowerCase().includes(caseNumber))
      );
    });
  };

  onMount(() => {
    onAuthStateChanged(auth, (user) => {
      if (!user) {
        goto('/login');
      } else {
        const today = new Date().toISOString().split('T')[0];
        searchCriteria.startDate = today;
        fetchData();
      }
    });
  });
</script>

<svelte:head>
  <title>Table Data</title>
</svelte:head>

<div class="table-container">
  <h1>Table Data</h1>

  <div class="search-criteria">
    <label for="startDate">Start Date</label>
    <input type="date" id="startDate" bind:value={searchCriteria.startDate} />

    <label for="endDate">End Date</label>
    <input type="date" id="endDate" bind:value={searchCriteria.endDate} />

    <label for="advocateName">Advocate Name</label>
    <input type="text" id="advocateName" bind:value={searchCriteria.advocateName} />

    <label for="caseNumber">Case Number</label>
    <input type="text" id="caseNumber" bind:value={searchCriteria.caseNumber} />

    <button on:click={fetchData}>Search</button>
  </div>

  <table>
    <thead>
      <tr>
        <th>Date</th>
        <th>Case Type</th>
        <th>Case Number</th>
        <th>Case Year</th>
        <th>Advocate Name</th>
      </tr>
    </thead>
    <tbody>
      {#each filterData() as row}
        <tr>
          <td>{row.Date}</td>
          <td>{row['Case Type']}</td>
          <td>{row['Case Number']}</td>
          <td>{row['Case Year']}</td>
          <td>{row['Advocate Name']}</td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  .table-container {
    max-width: 800px;
    margin: 0 auto;
    padding: 1rem;
    border: 1px solid #ccc;
    border-radius: 4px;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
  }

  h1 {
    text-align: center;
  }

  .search-criteria {
    display: flex;
    flex-direction: column;
    margin-bottom: 1rem;
  }

  .search-criteria label {
    margin-bottom: 0.5rem;
  }

  .search-criteria input {
    margin-bottom: 1rem;
    padding: 0.5rem;
    border: 1px solid #ccc;
    border-radius: 4px;
  }

  .search-criteria button {
    padding: 0.5rem;
    border: none;
    border-radius: 4px;
    background-color: #007bff;
    color: white;
    cursor: pointer;
  }

  .search-criteria button:hover {
    background-color: #0056b3;
  }

  table {
    width: 100%;
    border-collapse: collapse;
  }

  th, td {
    padding: 0.5rem;
    border: 1px solid #ccc;
    text-align: left;
  }

  th {
    background-color: #f8f8f8;
  }
</style>

<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { auth } from '$lib/firebase';
  import { onAuthStateChanged } from 'firebase/auth';

  let file;
  let date;
  let dataframe = null;
  let error = '';
  let isUploading = false;
  let tableData = [];
  let editedData = [];
  let skipPreview = false;
  let successMessage = '';
  let showModal = false;

  const uploadFile = async () => {
    isUploading = true;
    console.log('File upload attempt:', file.name);
    const formData = new FormData();
    formData.append('file', file.files[0]);
    formData.append('date', date);
    formData.append('skip_preview', skipPreview);

    const maxRetries = 3;
    for (let attempt = 0; attempt < maxRetries; attempt++) {
      try {
        const response = await fetch('http://localhost:8000/upload-pdf', {
          method: 'POST',
          body: formData,
          credentials: 'include'
        });

        if (!response.ok) {
          throw new Error('Failed to upload file');
        }

        const data = await response.json();
        if (skipPreview) {
          successMessage = data.message;
        } else {
          dataframe = data;
          tableData = data.data;
          editedData = JSON.parse(JSON.stringify(tableData));
          showModal = true;
        }
        console.log('File upload successful:', file.name);
        break; // Exit the retry loop if successful
      } catch (e) {
        console.error('File upload failed:', file.name, 'error:', e.message);
        error = e.message;
        if (e.message.includes('Connection was reset by the remote host') && attempt < maxRetries - 1) {
          console.log(`Retrying file upload (attempt ${attempt + 2}/${maxRetries})...`);
          await new Promise(resolve => setTimeout(resolve, 1000)); // Wait for 1 second before retrying
        } else {
          break; // Exit the retry loop if not a ConnectionResetError or max retries reached
        }
      } finally {
        isUploading = false;
      }
    }
  };

  const saveData = async () => {
    try {
      const response = await fetch('http://localhost:8000/save-data', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ "data": editedData }),
        credentials: 'include'
      });

      if (!response.ok) {
        throw new Error('Failed to save data');
      }

      const result = await response.json();
      console.log('Data saved successfully:', result);
    } catch (e) {
      console.error('Failed to save data:', e.message);
      error = e.message;
    }
  };

  const cancelEdit = () => {
    editedData = JSON.parse(JSON.stringify(tableData));
  };

  const addRow = () => {
    editedData.push({});
  };

  const deleteRow = (index) => {
    editedData.splice(index, 1);
  };

  const toggleEdit = (index) => {
    editedData[index].isEditable = !editedData[index].isEditable;
  };

  onMount(() => {
    onAuthStateChanged(auth, (user) => {
      if (!user) {
        goto('/login');
      }
    });
  });
</script>

<svelte:head>
  <title>Upload PDF</title>
</svelte:head>

<div class="upload-container">
  <h1>Upload PDF</h1>
  <form on:submit|preventDefault={uploadFile}>
    <div>
      <label for="file">Choose PDF file</label>
      <input type="file" id="file" accept="application/pdf" bind:this={file} required />
    </div>
    <div>
      <label for="date">Date</label>
      <input type="date" id="date" bind:value={date} required pattern="\d{4}-\d{2}-\d{2}" />
    </div>
    <div>
      <label for="skipPreview">Skip Preview</label>
      <input type="checkbox" id="skipPreview" bind:checked={skipPreview} />
    </div>
    {#if error}
      <p class="error">{error}</p>
    {/if}
    <button type="submit" disabled={isUploading}>Upload</button>
  </form>

  {#if successMessage}
    <p class="success">{successMessage}</p>
  {/if}

  {#if showModal}
    <div class="modal">
      <div class="modal-content">
        <span class="close" on:click={() => showModal = false}>&times;</span>
        <h2>Dataframe</h2>
        <table>
          <thead>
            <tr>
              {#each Object.keys(editedData[0] || {}) as key}
                <th>{key}</th>
              {/each}
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {#each editedData as row, index}
              <tr>
                {#each Object.keys(row) as key}
                  <td>
                    <input
                      type="text"
                      bind:value={row[key]}
                      readonly={!row.isEditable}
                      class="table-input"
                    />
                  </td>
                {/each}
                <td>
                  <!-- Icon button for Edit -->
                  <button
                    on:click={() => toggleEdit(index)}
                    class="icon-button"
                    title={row.isEditable ? 'Save' : 'Edit'}
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      class="icon"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        stroke-width="2"
                        d="M11 17l-4 4m0 0l4-4m-4 4V3m13 13l-4 4m0 0l4-4m-4 4V3"
                      />
                    </svg>
                  </button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
        <div class="button-row">
          <button on:click={addRow}>Add Row</button>
          <button on:click={saveData}>Save</button>
          <button on:click={cancelEdit}>Cancel</button>
          <button on:click={() => deleteRow()} class="delete-row">Delete Row</button>
        </div>
      </div>
    </div>
  {/if}
</div>

<style>
  .upload-container {
    max-width: 600px;
    margin: 0 auto;
    padding: 1rem;
    border: 1px solid #ccc;
    border-radius: 4px;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    background-color: #fff;
  }

  h1 {
    text-align: center;
    color: #333;
  }

  form {
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  label {
    margin-bottom: 0.5rem;
    color: #333;
  }

  input {
    margin-bottom: 1rem;
    padding: 0.5rem;
    border: 1px solid #ccc;
    border-radius: 4px;
    width: 100%;
  }

  .error {
    color: red;
    margin-bottom: 1rem;
  }

  .success {
    color: green;
    margin-bottom: 1rem;
  }

  button {
    padding: 0.5rem;
    border: none;
    border-radius: 4px;
    background-color: #007bff;
    color: white;
    cursor: pointer;
    width: 100%;
  }

  button:hover {
    background-color: #0056b3;
  }

  .modal {
    display: block;
    position: fixed;
    z-index: 1;
    left: 0;
    top: 0;
    width: 100%;
    height: 100%;
    overflow: auto;
    background-color: rgb(0,0,0);
    background-color: rgba(0,0,0,0.4);
  }

  .modal-content {
    background-color: #fefefe;
    margin: 15% auto;
    padding: 20px;
    border: 1px solid #888;
    width: 80%;
    overflow-y: auto;
    max-height: 80vh;
  }

  .close {
    color: #aaa;
    float: right;
    font-size: 28px;
    font-weight: bold;
  }

  .close:hover,
  .close:focus {
    color: black;
    text-decoration: none;
    cursor: pointer;
  }

  .dataframe {
    margin-top: 1rem;
    width: 100%;
  }

  /* Reduce row width */
  table {
    width: 100%;
    border-collapse: collapse;
    table-layout: fixed; /* Ensures consistent column width */
  }

  th,
  td {
    padding: 0.3rem; /* Reduce padding */
    border: 1px solid #ccc;
    text-align: left;
    word-wrap: break-word; /* Prevent overflow */
  }

  th {
    background-color: #f8f8f8;
  }

  /* Style for the input fields in the table */
  .table-input {
    width: 100%;
    padding: 0.2rem; /* Reduce padding */
    border: none;
    background-color: transparent;
  }

  .table-input[readonly] {
    color: #666; /* Dim readonly inputs */
  }

  /* Icon button styling */
  .icon-button {
    background: none;
    border: none;
    cursor: pointer;
    padding: 0.2rem; /* Reduce padding */
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .icon-button:hover {
    background-color: #f0f0f0;
    border-radius: 4px;
  }

  /* Reduce icon size */
  .icon {
    width: 16px; /* Smaller size */
    height: 16px;
    color: #007bff; /* Blue color */
  }

  .icon-button:hover .icon {
    color: #0056b3; /* Darker blue on hover */
  }

  .button-row {
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
    margin-top: 1rem;
  }

  .button-row button {
    padding: 0.3rem 0.6rem;
    font-size: 0.9rem;
    border-radius: 4px;
  }

  .delete-row {
    background-color: #ff4d4d;
    color: white;
  }

  .delete-row:hover {
    background-color: #cc0000;
  }
</style>

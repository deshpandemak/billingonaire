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
    } catch (e) {
      console.error('File upload failed:', file.name, 'error:', e.message);
      error = e.message;
    } finally {
      isUploading = false;
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
      <input type="date" id="date" bind:value={date} required />
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
                    <input type="text" bind:value={row[key]} readonly={!row.isEditable} />
                  </td>
                {/each}
                <td>
                  <button on:click={() => toggleEdit(index)}>{row.isEditable ? 'Save' : 'Edit'}</button>
                  <button on:click={() => deleteRow(index)}>Delete</button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
        <button on:click={addRow}>Add Row</button>
        <button on:click={saveData}>Save</button>
        <button on:click={cancelEdit}>Cancel</button>
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

  pre {
    background-color: #f8f8f8;
    padding: 1rem;
    border-radius: 4px;
    overflow-x: auto;
    width: 100%;
  }
</style>

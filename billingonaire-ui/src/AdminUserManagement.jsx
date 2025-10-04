import React, { useState, useEffect, useCallback } from 'react';
import { auth } from './lib/firebase';
import { onAuthStateChanged } from 'firebase/auth';
import { authenticatedFetchJSON } from './lib/api';
import './styles/professional.css';

const AdminUserManagement = () => {
  const [user, setUser] = useState(null);
  const [profile, setProfile] = useState(null);
  const [users, setUsers] = useState([]);
  const [availableRoles, setAvailableRoles] = useState({});
  const [availableLegalCategories, setAvailableLegalCategories] = useState({});
  const [unsyncedUsers, setUnsyncedUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [syncLoading, setSyncLoading] = useState(false);
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [selectedUser, setSelectedUser] = useState(null);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showUnsyncedModal, setShowUnsyncedModal] = useState(false);
  const [roleFilter, setRoleFilter] = useState('');

  // Form state for editing users
  const [editForm, setEditForm] = useState({
    role: 'user',
    legal_category: 'assistant_government_pleader',
    full_name: '',
    is_active: true
  });

  // Form state for creating new users
  const [createForm, setCreateForm] = useState({
    email: '',
    role: 'user',
    legal_category: 'assistant_government_pleader',
    full_name: ''
  });

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, async (user) => {
      console.log('Auth state changed, user:', user?.email || 'No user');
      setUser(user);
      if (user) {
        console.log('User authenticated, loading profile and data...');
        await loadUserProfile();
        // Wait a bit for profile to load before loading users
        setTimeout(async () => {
          await loadUsers();
          await loadAvailableRoles();
          await loadAvailableLegalCategories();
          await loadUnsyncedUsers();
        }, 500);
      } else {
        console.log('No user authenticated');
      }
      setLoading(false);
    });
    return () => unsubscribe();
  }, [loadUsers]);

  const loadUserProfile = async () => {
    try {
      console.log('Loading user profile...');
      const profileData = await authenticatedFetchJSON('/user/profile');
      console.log('Profile data received:', profileData);
      setProfile(profileData);
      
      // Check if user is admin
      if (profileData.role !== 'admin') {
        console.log('User is not admin, role:', profileData.role);
        setError('Access denied. Administrator privileges required.');
        return;
      }
      
      console.log('User confirmed as admin, proceeding to load users');
    } catch (error) {
      console.error('Error loading profile:', error);
      setError('Failed to load user profile');
    }
  };

  const loadUsers = useCallback(async () => {
    try {
      setError('');
      const queryParams = roleFilter ? `?role_filter=${roleFilter}` : '';
      console.log('Loading users with query:', `/admin/users${queryParams}`);
      
      const usersData = await authenticatedFetchJSON(`/admin/users${queryParams}`);
      console.log('Users data received:', usersData);
      console.log('Users data type:', typeof usersData);
      console.log('Users data length:', Array.isArray(usersData) ? usersData.length : 'Not an array');
      
      // Ensure usersData is an array
      if (Array.isArray(usersData)) {
        setUsers(usersData);
        console.log(`Successfully loaded ${usersData.length} users`);
      } else {
        console.error('Expected array but got:', usersData);
        setUsers([]);
        setError('Invalid response format from server');
      }
    } catch (error) {
      console.error('Error loading users:', error);
      setError(`Failed to load users: ${error.message}`);
      setUsers([]); // Clear users on error
    }
  }, [roleFilter]);

  const loadAvailableRoles = async () => {
    try {
      const response = await authenticatedFetchJSON('/admin/available-roles');
      setAvailableRoles(response.roles || {});
      console.log('Available roles loaded:', response.roles);
    } catch (error) {
      console.error('Error loading available roles:', error);
    }
  };

  const loadAvailableLegalCategories = async () => {
    try {
      const response = await authenticatedFetchJSON('/admin/available-legal-categories');
      setAvailableLegalCategories(response.legal_categories || {});
      console.log('Available legal categories loaded:', response.legal_categories);
    } catch (error) {
      console.error('Error loading available legal categories:', error);
    }
  };

  const loadUnsyncedUsers = async () => {
    try {
      const unsyncedData = await authenticatedFetchJSON('/admin/unsynced-users');
      setUnsyncedUsers(unsyncedData || []);
      console.log('Unsynced users loaded:', unsyncedData.length);
    } catch (error) {
      console.error('Error loading unsynced users:', error);
    }
  };

  const handleSyncFirebaseUsers = async () => {
    try {
      setSyncLoading(true);
      setError('');
      setSuccessMessage('');
      
      const result = await authenticatedFetchJSON('/admin/sync-firebase-users', {
        method: 'POST'
      });
      
      console.log('Sync result:', result);
      
      if (result.synced_count > 0) {
        setSuccessMessage(`Successfully synced ${result.synced_count} Firebase users to the system.`);
        await loadUsers(); // Refresh the user list
        await loadUnsyncedUsers(); // Refresh unsynced users
      } else {
        setSuccessMessage('No new users found to sync. All Firebase users are already in the system.');
      }
      
      if (result.errors && result.errors.length > 0) {
        console.warn('Sync errors:', result.errors);
        setError(`Some users had errors: ${result.errors.join(', ')}`);
      }
      
    } catch (error) {
      console.error('Error syncing Firebase users:', error);
      setError(`Failed to sync Firebase users: ${error.message}`);
    } finally {
      setSyncLoading(false);
    }
  };

  const handleEditUser = (user) => {
    setSelectedUser(user);
    setEditForm({
      role: user.role || 'user',
      legal_category: user.legal_category || 'assistant_government_pleader',
      full_name: user.full_name || '',
      is_active: user.is_active !== false
    });
    setShowEditModal(true);
  };

  const handleSaveUser = async () => {
    if (!selectedUser) return;

    try {
      setError('');
      setSuccessMessage('');

      // Update user role and basic info
      await authenticatedFetchJSON(`/admin/user/${selectedUser.uid}/role`, {
        method: 'POST',
        body: JSON.stringify({
          role: editForm.role,
          legal_category: editForm.legal_category,
          full_name: editForm.full_name,
          is_active: editForm.is_active
        })
      });

      setSuccessMessage('User updated successfully');
      setShowEditModal(false);
      await loadUsers(); // Refresh the user list
    } catch (error) {
      console.error('Error updating user:', error);
      setError(`Failed to update user: ${error.message}`);
    }
  };

  const handleCreateUser = async () => {
    try {
      setError('');
      setSuccessMessage('');

      if (!createForm.email.trim()) {
        setError('Email is required');
        return;
      }

      const userData = {
        email: createForm.email.trim(),
        role: createForm.role,
        legal_category: createForm.legal_category || undefined,
        full_name: createForm.full_name.trim()
      };

      const result = await authenticatedFetchJSON('/admin/create-user', {
        method: 'POST',
        body: JSON.stringify(userData)
      });

      setSuccessMessage(`User created successfully! Default password: ${result.default_password}`);
      setShowCreateModal(false);
      setCreateForm({
        email: '',
        role: 'user',
        legal_category: 'assistant_government_pleader',
        full_name: ''
      });
      await loadUsers(); // Refresh the user list
    } catch (error) {
      console.error('Error creating user:', error);
      setError(`Failed to create user: ${error.message}`);
    }
  };

  if (loading) {
    return (
      <div className="container-professional">
        <div className="text-center">
          <div className="spinner-border text-primary" role="status">
            <span className="visually-hidden">Loading...</span>
          </div>
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="container-professional">
        <div className="alert alert-warning">
          Please log in to access user management.
        </div>
      </div>
    );
  }

  if (profile && profile.role !== 'admin') {
    return (
      <div className="container-professional">
        <div className="alert alert-danger">
          <h5>Access Denied</h5>
          <p>Administrator privileges are required to access user management.</p>
          <p><strong>Your role:</strong> {profile.role || 'Unknown'}</p>
          <p><strong>Your email:</strong> {user?.email}</p>
          <button className="btn btn-primary" onClick={loadUserProfile}>
            🔄 Refresh Profile
          </button>
        </div>
      </div>
    );
  }

  // If profile is still loading or null, show loading message
  if (!profile) {
    return (
      <div className="container-professional">
        <div className="text-center">
          <div className="spinner-border text-primary" role="status">
            <span className="visually-hidden">Loading...</span>
          </div>
          <p className="mt-2">Loading user profile...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="container-professional">
      <div className="row">
        <div className="col-12">
          <div className="page-header">
            <h1 className="page-title">👥 User Management</h1>
            <p className="page-subtitle">Manage system users and their roles</p>
          </div>

          {error && (
            <div className="alert alert-danger" role="alert">
              {error}
            </div>
          )}

          {successMessage && (
            <div className="alert alert-success" role="alert">
              {successMessage}
            </div>
          )}

          {/* Filter Section */}
          <div className="card mb-4">
            <div className="card-body">
              <div className="row align-items-end">
                <div className="col-md-4">
                  <label className="form-label">Filter by Role</label>
                  <select 
                    className="form-control"
                    value={roleFilter}
                    onChange={(e) => {
                      setRoleFilter(e.target.value);
                      // Trigger re-load when filter changes
                      setTimeout(() => loadUsers(), 100);
                    }}
                  >
                    <option value="">All Users</option>
                    {Object.entries(availableRoles).map(([roleKey, displayName]) => (
                      <option key={roleKey} value={roleKey}>
                        {displayName}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="col-md-8">
                  <button 
                    className="btn btn-primary me-2"
                    onClick={loadUsers}
                  >
                    🔄 Refresh
                  </button>
                  <button 
                    className="btn btn-info me-2"
                    onClick={handleSyncFirebaseUsers}
                    disabled={syncLoading}
                  >
                    {syncLoading ? (
                      <>
                        <span className="spinner-border spinner-border-sm me-1" role="status"></span>
                        Syncing...
                      </>
                    ) : (
                      <>🔄 Sync Firebase Users</>
                    )}
                  </button>
                  {unsyncedUsers.length > 0 && (
                    <button 
                      className="btn btn-warning me-2"
                      onClick={() => setShowUnsyncedModal(true)}
                    >
                      ⚠️ View Unsynced ({unsyncedUsers.length})
                    </button>
                  )}
                  <button 
                    className="btn btn-success"
                    onClick={() => setShowCreateModal(true)}
                  >
                    ➕ Add New User
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Users Table */}
          <div className="card">
            <div className="card-header">
              <h5 className="card-title mb-0">System Users ({users.length})</h5>
            </div>
            <div className="card-body">
              {loading ? (
                <div className="text-center py-4">
                  <div className="spinner-border text-primary" role="status">
                    <span className="visually-hidden">Loading...</span>
                  </div>
                  <p className="mt-2 text-muted">Loading users...</p>
                </div>
              ) : users.length === 0 ? (
                <div className="text-center py-4">
                  <p className="text-muted">No users found</p>
                  <button className="btn btn-sm btn-outline-primary" onClick={loadUsers}>
                    🔄 Try Again
                  </button>
                </div>
              ) : (
                <div className="table-responsive">
                  <table className="table table-hover">
                    <thead>
                      <tr>
                        <th>Email</th>
                        <th>Full Name</th>
                        <th>Role</th>
                        <th>Legal Category</th>
                        <th>Status</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {users.map((user) => (
                        <tr key={user.uid}>
                          <td>
                            <strong>{user.email}</strong>
                            {user.email === 'deshpande.mak@gmail.com' && (
                              <span className="badge bg-warning ms-2">Initial Admin</span>
                            )}
                          </td>
                          <td>{user.full_name || '-'}</td>
                          <td>
                            <span className={`role-badge ${user.role}`}>
                              {user.role === 'admin' ? 'Administrator' : 'User'}
                            </span>
                          </td>
                          <td>
                            {user.legal_category ? (
                              <span className="badge bg-info text-dark">
                                {availableLegalCategories[user.legal_category] || user.legal_category}
                              </span>
                            ) : (
                              <span className="text-muted">Not set</span>
                            )}
                          </td>
                          <td>
                            <span className={`badge ${user.is_active !== false ? 'bg-success' : 'bg-danger'}`}>
                              {user.is_active !== false ? 'Active' : 'Disabled'}
                            </span>
                          </td>
                          <td>
                            <button 
                              className="btn btn-sm btn-outline-primary"
                              onClick={() => handleEditUser(user)}
                            >
                              ✏️ Edit
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Create User Modal */}
      {showCreateModal && (
        <div className="modal show d-block" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}>
          <div className="modal-dialog modal-lg">
            <div className="modal-content">
              <div className="modal-header">
                <h5 className="modal-title">Create New User</h5>
                <button 
                  type="button" 
                  className="btn-close"
                  onClick={() => setShowCreateModal(false)}
                ></button>
              </div>
              <div className="modal-body">
                <form>
                  <div className="mb-3">
                    <label className="form-label">Email Address *</label>
                    <input
                      type="email"
                      className="form-control"
                      value={createForm.email}
                      onChange={(e) => setCreateForm({...createForm, email: e.target.value})}
                      placeholder="user@example.com"
                      required
                    />
                    <small className="form-text text-muted">
                      User will receive login credentials at this email
                    </small>
                  </div>

                  <div className="mb-3">
                    <label className="form-label">Full Name</label>
                    <input
                      type="text"
                      className="form-control"
                      value={createForm.full_name}
                      onChange={(e) => setCreateForm({...createForm, full_name: e.target.value})}
                      placeholder="Enter full name"
                    />
                  </div>

                  <div className="mb-3">
                    <label className="form-label">Role *</label>
                    <select
                      className="form-control"
                      value={createForm.role}
                      onChange={(e) => setCreateForm({...createForm, role: e.target.value})}
                    >
                      {Object.entries(availableRoles).map(([roleKey, displayName]) => (
                        <option key={roleKey} value={roleKey}>
                          {displayName}
                        </option>
                      ))}
                    </select>
                    <small className="form-text text-muted">
                      Role is used for access control only (Admin or User)
                    </small>
                  </div>

                  <div className="mb-3">
                    <label className="form-label">Legal Category {createForm.role === 'admin' ? '(Optional)' : '*'}</label>
                    <select
                      className="form-control"
                      value={createForm.legal_category}
                      onChange={(e) => setCreateForm({...createForm, legal_category: e.target.value})}
                    >
                      {createForm.role === 'admin' && (
                        <option value="">No legal category</option>
                      )}
                      {Object.entries(availableLegalCategories).map(([categoryKey, displayName]) => (
                        <option key={categoryKey} value={categoryKey}>
                          {displayName}
                        </option>
                      ))}
                    </select>
                    <small className="form-text text-muted">
                      Legal category for professional classification (applies to both administrators and users)
                    </small>
                  </div>

                  <div className="alert alert-info">
                    <strong>📝 Default Login Credentials:</strong><br/>
                    • Email: {createForm.email || '[email will be shown here]'}<br/>
                    • Password: <code>password123</code><br/>
                    <small>User should change password on first login</small>
                  </div>
                </form>
              </div>
              <div className="modal-footer">
                <button 
                  type="button" 
                  className="btn btn-secondary"
                  onClick={() => setShowCreateModal(false)}
                >
                  Cancel
                </button>
                <button 
                  type="button" 
                  className="btn btn-success"
                  onClick={handleCreateUser}
                  disabled={!createForm.email.trim()}
                >
                  Create User
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Edit User Modal */}
      {showEditModal && selectedUser && (
        <div className="modal show d-block" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}>
          <div className="modal-dialog modal-lg">
            <div className="modal-content">
              <div className="modal-header">
                <h5 className="modal-title">Edit User: {selectedUser.email}</h5>
                <button 
                  type="button" 
                  className="btn-close"
                  onClick={() => setShowEditModal(false)}
                ></button>
              </div>
              <div className="modal-body">
                <form>
                  <div className="mb-3">
                    <label className="form-label">Full Name</label>
                    <input
                      type="text"
                      className="form-control"
                      value={editForm.full_name}
                      onChange={(e) => setEditForm({...editForm, full_name: e.target.value})}
                    />
                  </div>

                  <div className="mb-3">
                    <label className="form-label">Role</label>
                    <select
                      className="form-control"
                      value={editForm.role}
                      onChange={(e) => setEditForm({...editForm, role: e.target.value})}
                    >
                      {Object.entries(availableRoles).map(([roleKey, displayName]) => (
                        <option key={roleKey} value={roleKey}>
                          {displayName}
                        </option>
                      ))}
                    </select>
                    <small className="form-text text-muted">
                      Role is used for access control only (Admin or User)
                    </small>
                  </div>

                  <div className="mb-3">
                    <label className="form-label">Legal Category {editForm.role === 'admin' ? '(Optional)' : ''}</label>
                    <select
                      className="form-control"
                      value={editForm.legal_category || ''}
                      onChange={(e) => setEditForm({...editForm, legal_category: e.target.value})}
                    >
                      {editForm.role === 'admin' && (
                        <option value="">No legal category</option>
                      )}
                      {Object.entries(availableLegalCategories).map(([categoryKey, displayName]) => (
                        <option key={categoryKey} value={categoryKey}>
                          {displayName}
                        </option>
                      ))}
                    </select>
                    <small className="form-text text-muted">
                      Legal category for professional classification (applies to both administrators and users)
                    </small>
                  </div>

                  <div className="mb-3">
                    <div className="form-check">
                      <input
                        className="form-check-input"
                        type="checkbox"
                        id="is_active"
                        checked={editForm.is_active}
                        onChange={(e) => setEditForm({...editForm, is_active: e.target.checked})}
                      />
                      <label className="form-check-label" htmlFor="is_active">
                        Account is active
                      </label>
                    </div>
                    <small className="form-text text-muted">
                      Disabled accounts cannot access the system
                    </small>
                  </div>
                </form>
              </div>
              <div className="modal-footer">
                <button 
                  type="button" 
                  className="btn btn-secondary"
                  onClick={() => setShowEditModal(false)}
                >
                  Cancel
                </button>
                <button 
                  type="button" 
                  className="btn btn-primary"
                  onClick={handleSaveUser}
                >
                  Save Changes
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Unsynced Firebase Users Modal */}
      {showUnsyncedModal && (
        <div className="modal show d-block" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}>
          <div className="modal-dialog modal-lg">
            <div className="modal-content">
              <div className="modal-header">
                <h5 className="modal-title">🔄 Unsynced Firebase Users</h5>
                <button 
                  type="button" 
                  className="btn-close"
                  onClick={() => setShowUnsyncedModal(false)}
                ></button>
              </div>
              <div className="modal-body">
                <p className="text-muted mb-3">
                  These users exist in Firebase Authentication but don't have profiles in the system yet. 
                  Click "Sync Firebase Users" to import them.
                </p>
                
                {unsyncedUsers.length === 0 ? (
                  <div className="alert alert-success">
                    <h6>✅ All Firebase users are synced!</h6>
                    <p className="mb-0">All users from Firebase Authentication have been successfully imported to the system.</p>
                  </div>
                ) : (
                  <div className="table-responsive">
                    <table className="table table-striped">
                      <thead>
                        <tr>
                          <th>Email</th>
                          <th>Display Name</th>
                          <th>Created</th>
                          <th>Last Sign In</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {unsyncedUsers.map((user, index) => (
                          <tr key={user.uid || index}>
                            <td>
                              <strong>{user.email}</strong>
                              <br />
                              <small className="text-muted">UID: {user.uid}</small>
                            </td>
                            <td>{user.display_name || <em className="text-muted">Not set</em>}</td>
                            <td>
                              {user.created ? (
                                <small>{user.created}</small>
                              ) : (
                                <em className="text-muted">Unknown</em>
                              )}
                            </td>
                            <td>
                              {user.last_sign_in ? (
                                <small>{user.last_sign_in}</small>
                              ) : (
                                <em className="text-muted">Never</em>
                              )}
                            </td>
                            <td>
                              {user.disabled ? (
                                <span className="badge bg-danger">Disabled</span>
                              ) : (
                                <span className="badge bg-success">Active</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
              <div className="modal-footer">
                <button 
                  type="button" 
                  className="btn btn-secondary"
                  onClick={() => setShowUnsyncedModal(false)}
                >
                  Close
                </button>
                {unsyncedUsers.length > 0 && (
                  <button 
                    type="button" 
                    className="btn btn-primary"
                    onClick={() => {
                      setShowUnsyncedModal(false);
                      handleSyncFirebaseUsers();
                    }}
                    disabled={syncLoading}
                  >
                    {syncLoading ? 'Syncing...' : `🔄 Sync All ${unsyncedUsers.length} Users`}
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminUserManagement;
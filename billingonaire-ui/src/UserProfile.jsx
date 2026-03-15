import React, { useState, useEffect } from 'react';
import { auth } from './lib/firebase';
import { onAuthStateChanged } from 'firebase/auth';
import { authenticatedFetchJSON } from './lib/api';
import './styles/professional.css';

const UserProfile = () => {
  const [user, setUser] = useState(null);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');

  // Form states
  const [profileForm, setProfileForm] = useState({
    role: 'user',
    full_name: ''
  });

  const [passwordForm, setPasswordForm] = useState({
    new_password: '',
    confirm_password: ''
  });

  const [showPasswordForm, setShowPasswordForm] = useState(false);

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, async (user) => {
      setUser(user);
      if (user) {
        await loadUserProfile();
      }
      setLoading(false);
    });
    return () => unsubscribe();
  }, []);

  const loadUserProfile = async () => {
    try {
      // Double-check authentication state before making API call
      if (!auth.currentUser) {
        console.log('⚠️ UserProfile: User not authenticated, skipping profile load');
        setError('Please log in to view your profile');
        return;
      }

      console.log('📡 UserProfile: Loading profile for user:', auth.currentUser.email);
      const profileData = await authenticatedFetchJSON('/user/profile');
      console.log('✅ UserProfile: Profile loaded successfully:', profileData);

      setProfile(profileData);
      setError(''); // Clear any previous errors

      setProfileForm({
        role: profileData.role || 'user',
        full_name: profileData.full_name || ''
      });
    } catch (error) {
      console.error('❌ UserProfile: Error loading profile:', error);

      // Provide more specific error messages
      if (error.message.includes('User not authenticated')) {
        setError('Please log in to view your profile');
      } else if (error.message.includes('401')) {
        setError('Session expired. Please log in again.');
      } else if (error.message.includes('403')) {
        setError('Your account has been disabled. Contact support.');
      } else if (error.message.includes('Network') || error.message.includes('fetch')) {
        setError('Network error. Please check your connection and try again.');
      } else {
        setError(`Failed to load user profile: ${error.message}`);
      }
    }
  };

  const handleProfileSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSuccessMessage('');

    try {
      const updatedProfile = await authenticatedFetchJSON('/user/profile', {
        method: 'POST',
        body: JSON.stringify(profileForm)
      });

      setProfile(updatedProfile);
      setSuccessMessage('Profile updated successfully!');
    } catch (error) {
      console.error('Error updating profile:', error);
      setError('Failed to update profile');
    }
  };

  const handlePasswordSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSuccessMessage('');

    if (passwordForm.new_password !== passwordForm.confirm_password) {
      setError('Passwords do not match');
      return;
    }

    if (passwordForm.new_password.length < 6) {
      setError('Password must be at least 6 characters');
      return;
    }

    try {
      await authenticatedFetchJSON('/user/change-password', {
        method: 'POST',
        body: JSON.stringify({ new_password: passwordForm.new_password })
      });

      setSuccessMessage('Password changed successfully!');
      setPasswordForm({ new_password: '', confirm_password: '' });
      setShowPasswordForm(false);
    } catch (error) {
      console.error('Error changing password:', error);
      setError('Failed to change password');
    }
  };

  if (loading) {
    return (
      <div className="dashboard-container">
        <div className="loading-container">
          <div className="loading"></div>
          <p>Loading profile...</p>
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="dashboard-container">
        <div className="alert-error">
          <strong>Authentication Required:</strong> Please log in to view your profile.
        </div>
      </div>
    );
  }

  return (
    <div className="dashboard-container">
      <div className="dashboard-header">
        <h1 className="dashboard-title">User Profile</h1>
        <p className="dashboard-subtitle">
          Manage your account settings and role assignments
        </p>
      </div>

      {error && (
        <div className="alert-error">
          <strong>Error:</strong> {error}
        </div>
      )}

      {successMessage && (
        <div className="alert-success">
          <strong>Success:</strong> {successMessage}
        </div>
      )}

      <div className="dashboard-grid">
        {/* Profile Information */}
        <div className="card-professional">
          <div className="card-header">
            <h2 className="section-title">👤 Profile Information</h2>
          </div>
          <div className="card-body">
            <form onSubmit={handleProfileSubmit}>
              <div className="form-group">
                <label className="form-label">Email Address</label>
                <input
                  type="email"
                  className="form-control"
                  value={user.email || ''}
                  disabled
                />
                <small style={{ color: 'var(--gray-500)', fontSize: '0.875rem' }}>
                  Email cannot be changed
                </small>
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="full_name">Full Name</label>
                <input
                  id="full_name"
                  type="text"
                  className="form-control"
                  value={profileForm.full_name}
                  onChange={(e) => setProfileForm({...profileForm, full_name: e.target.value})}
                  required
                />
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="role">Role</label>
                <select
                  id="role"
                  className="form-control"
                  value={profileForm.role}
                  onChange={(e) => setProfileForm({...profileForm, role: e.target.value})}
                  disabled={profile && !profile.needs_setup && profile.role !== 'admin'}
                >
                  <option value="user">User</option>
                  <option value="admin">Administrator</option>
                </select>
                {profile && !profile.needs_setup && profile.role !== 'admin' && (
                  <small style={{ color: 'var(--gray-500)', fontSize: '0.875rem' }}>
                    Contact an administrator to change your role
                  </small>
                )}
              </div>

              <button type="submit" className="btn-professional btn-primary">
                {profile?.needs_setup ? 'Set Up Profile' : 'Update Profile'}
              </button>
            </form>
          </div>
        </div>

        {/* Password Management */}
        <div className="card-professional">
          <div className="card-header">
            <h2 className="section-title">🔒 Password Management</h2>
          </div>
          <div className="card-body">
            {!showPasswordForm ? (
              <div>
                <p style={{ color: 'var(--gray-600)', marginBottom: 'var(--spacing-lg)' }}>
                  Change your account password for enhanced security.
                </p>
                <button
                  className="btn-professional btn-secondary"
                  onClick={() => setShowPasswordForm(true)}
                >
                  Change Password
                </button>
              </div>
            ) : (
              <form onSubmit={handlePasswordSubmit}>
                <div className="form-group">
                  <label className="form-label" htmlFor="new_password">New Password</label>
                  <input
                    id="new_password"
                    type="password"
                    className="form-control"
                    value={passwordForm.new_password}
                    onChange={(e) => setPasswordForm({...passwordForm, new_password: e.target.value})}
                    minLength="6"
                    required
                  />
                </div>

                <div className="form-group">
                  <label className="form-label" htmlFor="confirm_password">Confirm Password</label>
                  <input
                    id="confirm_password"
                    type="password"
                    className="form-control"
                    value={passwordForm.confirm_password}
                    onChange={(e) => setPasswordForm({...passwordForm, confirm_password: e.target.value})}
                    minLength="6"
                    required
                  />
                </div>

                <div style={{ display: 'flex', gap: 'var(--spacing-md)' }}>
                  <button type="submit" className="btn-professional btn-primary">
                    Change Password
                  </button>
                  <button
                    type="button"
                    className="btn-professional btn-secondary"
                    onClick={() => {
                      setShowPasswordForm(false);
                      setPasswordForm({ new_password: '', confirm_password: '' });
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>

        {/* Current Profile Status */}
        {profile && !profile.needs_setup && (
          <div className="card-professional">
            <div className="card-header">
              <h2 className="section-title">📋 Current Status</h2>
            </div>
            <div className="card-body">
              <div className="profile-status">
                <div className="status-item">
                  <strong>Role:</strong>
                  <span className={`role-badge ${profile.role}`}>
                    {profile.role === 'admin' ? 'Administrator' : 'AGP User'}
                  </span>
                </div>

                {profile.role === 'agp' && profile.agp_name && (
                  <div className="status-item">
                    <strong>AGP Assignment:</strong>
                    <span>{profile.agp_name}</span>
                  </div>
                )}

                <div className="status-item">
                  <strong>Account Status:</strong>
                  <span className="status-active">Active</span>
                </div>

                {profile.created_at && (
                  <div className="status-item">
                    <strong>Member Since:</strong>
                    <span>{new Date(profile.created_at).toLocaleDateString()}</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default UserProfile;

from firebase_admin import firestore, auth
from fastapi import HTTPException
from datetime import datetime
import logging
from typing import Dict, List, Optional

class UserManager:
    def __init__(self):
        self.db = firestore.client()
        self.users_collection = "users"
    
    def setup_initial_admin(self) -> Dict:
        """
        Set up deshpande.mak@gmail.com as the initial system administrator
        """
        admin_email = "deshpande.mak@gmail.com"
        try:
            # Check if admin already exists
            admin_users = list(self.db.collection(self.users_collection)
                              .where("email", "==", admin_email)
                              .where("role", "==", "admin")
                              .limit(1)
                              .stream())
            
            if admin_users:
                logging.info(f"Initial admin {admin_email} already exists")
                return admin_users[0].to_dict()
            
            # Find user by email if exists
            existing_users = list(self.db.collection(self.users_collection)
                                 .where("email", "==", admin_email)
                                 .limit(1)
                                 .stream())
            
            if existing_users:
                # Update existing user to admin
                user_doc = existing_users[0]
                user_ref = self.db.collection(self.users_collection).document(user_doc.id)
                user_ref.update({
                    "role": "admin",
                    "agp_names": [],  # Admins don't need AGP names
                    "updated_at": datetime.now()
                })
                logging.info(f"Updated existing user {admin_email} to admin role")
                return user_ref.get().to_dict()
            else:
                logging.info(f"User {admin_email} does not exist in the system yet")
                return {"message": f"User {admin_email} needs to log in first to be made admin"}
                
        except Exception as e:
            logging.error(f"Error setting up initial admin: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error setting up admin: {str(e)}")
    
    def create_user_profile(self, uid: str, email: str, role: str = "agp", agp_names: List[str] = None, full_name: str = None) -> Dict:
        """
        Create or update user profile in Firestore
        
        Args:
            uid: Firebase UID
            email: User email
            role: 'admin' or 'agp'
            agp_names: List of AGP names for AGP users (can be multiple)
            full_name: User's full name
        """
        try:
            # Check if this is the initial admin setup
            if email == "deshpande.mak@gmail.com":
                role = "admin"
                agp_names = []  # Admins don't need AGP names
            elif role == "agp" and not agp_names:
                # For regular AGP users, they can be created without AGP names initially
                # Admin will assign AGP names later
                agp_names = []
            
            user_data = {
                "uid": uid,
                "email": email,
                "role": role,
                "agp_names": agp_names or [],  # Support multiple AGP names
                "full_name": full_name or email.split("@")[0],
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "is_active": True
            }
            
            # Store user profile
            user_ref = self.db.collection(self.users_collection).document(uid)
            user_ref.set(user_data)
            
            logging.info(f"User profile created for {email} with role {role}")
            return user_data
            
        except Exception as e:
            logging.error(f"Error creating user profile: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error creating user profile: {str(e)}")
    
    def get_user_profile(self, uid: str) -> Dict:
        """Get user profile by UID"""
        try:
            user_ref = self.db.collection(self.users_collection).document(uid)
            user_doc = user_ref.get()
            
            if not user_doc.exists:
                # Return default profile for backward compatibility
                firebase_user = auth.get_user(uid)
                # Check if this is the initial admin
                if firebase_user.email == "deshpande.mak@gmail.com":
                    return {
                        "uid": uid,
                        "email": firebase_user.email,
                        "role": "admin",
                        "agp_names": [],
                        "full_name": firebase_user.email.split("@")[0] if firebase_user.email else "Unknown",
                        "is_active": True,
                        "needs_setup": True  # Flag to show setup is needed
                    }
                else:
                    return {
                        "uid": uid,
                        "email": firebase_user.email,
                        "role": "agp",  # Default to AGP
                        "agp_names": [],  # Start with empty AGP names
                        "full_name": firebase_user.email.split("@")[0] if firebase_user.email else "Unknown",
                        "is_active": True,
                        "needs_setup": True  # Flag to show setup is needed
                    }
            
            user_data = user_doc.to_dict()
            # Convert Firestore timestamp to string for JSON serialization
            if 'created_at' in user_data and hasattr(user_data['created_at'], 'strftime'):
                user_data['created_at'] = user_data['created_at'].strftime('%Y-%m-%d %H:%M:%S')
            if 'updated_at' in user_data and hasattr(user_data['updated_at'], 'strftime'):
                user_data['updated_at'] = user_data['updated_at'].strftime('%Y-%m-%d %H:%M:%S')
            
            return user_data
            
        except Exception as e:
            logging.error(f"Error getting user profile: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error getting user profile: {str(e)}")
    
    def update_user_profile(self, uid: str, updates: Dict) -> Dict:
        """Update user profile (self-service safe fields only)"""
        try:
            # SECURITY: Only allow safe fields for self-service updates
            allowed_updates = ['full_name', 'is_active']
            filtered_updates = {k: v for k, v in updates.items() if k in allowed_updates}
            filtered_updates['updated_at'] = datetime.now()
            
            user_ref = self.db.collection(self.users_collection).document(uid)
            user_ref.update(filtered_updates)
            
            logging.info(f"User profile updated for {uid}")
            return self.get_user_profile(uid)
            
        except Exception as e:
            logging.error(f"Error updating user profile: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error updating user profile: {str(e)}")
    
    def get_all_agp_names(self) -> List[str]:
        """Get list of all AGP names from user profiles and board data"""
        try:
            agp_names = set()
            
            # Get AGP names from user profiles (supporting multiple AGP names per user)
            users_query = self.db.collection(self.users_collection).where("role", "==", "agp").stream()
            for user_doc in users_query:
                user_data = user_doc.to_dict()
                # Handle both old single agp_name and new multiple agp_names
                if user_data.get('agp_names'):
                    for agp_name in user_data['agp_names']:
                        if agp_name:
                            agp_names.add(agp_name)
                elif user_data.get('agp_name'):  # Backward compatibility
                    agp_names.add(user_data['agp_name'])
            
            # Get AGP names from board data (respondent_lawyer field)
            boards_query = self.db.collection("daily-boards").limit(100).stream()
            for board_doc in boards_query:
                board_data = board_doc.to_dict()
                respondent_lawyer = board_data.get('respondent_lawyer', '').strip()
                if respondent_lawyer and len(respondent_lawyer) > 3:  # Filter out short/empty names
                    agp_names.add(respondent_lawyer)
            
            return sorted(list(agp_names))
            
        except Exception as e:
            logging.error(f"Error getting AGP names: {str(e)}")
            return []
    
    def admin_update_user_profile(self, target_uid: str, updates: Dict, admin_uid: str) -> Dict:
        """Admin-only update of user profile including role and AGP assignments"""
        try:
            # Verify admin permissions
            if not self.is_admin(admin_uid):
                raise HTTPException(status_code=403, detail="Admin access required")
            
            # Allow admin to update role and AGP assignments
            allowed_updates = ['role', 'agp_names', 'full_name', 'is_active']
            filtered_updates = {k: v for k, v in updates.items() if k in allowed_updates}
            filtered_updates['updated_at'] = datetime.now()
            
            # Handle AGP names - ensure it's a list
            if 'agp_names' in filtered_updates:
                agp_names = filtered_updates['agp_names']
                if isinstance(agp_names, str):
                    filtered_updates['agp_names'] = [agp_names] if agp_names else []
                elif not isinstance(agp_names, list):
                    filtered_updates['agp_names'] = []
            
            user_ref = self.db.collection(self.users_collection).document(target_uid)
            user_ref.update(filtered_updates)
            
            logging.info(f"Admin {admin_uid} updated profile for {target_uid}")
            return self.get_user_profile(target_uid)
            
        except Exception as e:
            logging.error(f"Error in admin profile update: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error updating user profile: {str(e)}")
    
    def list_users(self, role_filter: str = None) -> List[Dict]:
        """List all users with optional role filter"""
        try:
            query = self.db.collection(self.users_collection)
            if role_filter:
                query = query.where("role", "==", role_filter)
            
            users = []
            for user_doc in query.stream():
                user_data = user_doc.to_dict()
                # Convert timestamps to strings
                if 'created_at' in user_data and hasattr(user_data['created_at'], 'strftime'):
                    user_data['created_at'] = user_data['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                if 'updated_at' in user_data and hasattr(user_data['updated_at'], 'strftime'):
                    user_data['updated_at'] = user_data['updated_at'].strftime('%Y-%m-%d %H:%M:%S')
                users.append(user_data)
            
            return users
            
        except Exception as e:
            logging.error(f"Error listing users: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error listing users: {str(e)}")
    
    def is_admin(self, uid: str) -> bool:
        """Check if user is admin"""
        try:
            user_profile = self.get_user_profile(uid)
            return user_profile.get('role') == 'admin'
        except:
            return False
    
    def get_user_agp_filter(self, uid: str) -> Optional[List[str]]:
        """Get the AGP filter for data access - returns None for admins, list of AGP names for AGP users"""
        try:
            profile = self.get_user_profile(uid)
            
            if not profile.get('is_active', True):
                raise HTTPException(status_code=403, detail="Account is disabled. Contact administrator.")
            
            role = profile.get('role')
            
            if role == 'admin':
                return None  # Admins can see all data
            elif role == 'agp':
                # Support both new agp_names and old agp_name for backward compatibility
                agp_names = profile.get('agp_names', [])
                if not agp_names and profile.get('agp_name'):
                    agp_names = [profile.get('agp_name')]
                
                if not agp_names:
                    raise HTTPException(status_code=403, detail="AGP assignment required. Please contact an administrator.")
                return agp_names
            else:
                raise HTTPException(status_code=403, detail="Invalid user role. Contact administrator.")
                
        except HTTPException:
            raise
        except Exception as e:
            logging.error(f"Error getting AGP filter: {str(e)}")
            raise HTTPException(status_code=500, detail="Error checking user permissions")
    
    def can_access_agp_data(self, uid: str, agp_name: str) -> bool:
        """Check if user can access data for specific AGP"""
        try:
            user_profile = self.get_user_profile(uid)
            
            # Admins can access all data
            if user_profile.get('role') == 'admin':
                return True
            
            # AGP users can access data for any of their assigned AGP names
            if user_profile.get('role') == 'agp':
                # Support both new agp_names and old agp_name for backward compatibility
                agp_names = user_profile.get('agp_names', [])
                if not agp_names and user_profile.get('agp_name'):
                    agp_names = [user_profile.get('agp_name')]
                
                return agp_name in agp_names
            
            return False
            
        except:
            return False
    

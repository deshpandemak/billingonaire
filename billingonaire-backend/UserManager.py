from firebase_admin import firestore, auth
from fastapi import HTTPException
from datetime import datetime
import logging
from typing import Dict, List, Optional

class UserManager:
    def __init__(self):
        self.db = firestore.client()
        self.users_collection = "users"
        
        # Define valid access control roles (for authorization)
        self.valid_roles = ["admin", "user"]
        self.role_display_names = {
            "admin": "Administrator",
            "user": "User"
        }
        
        # Define legal professional categories (separate from access control)
        self.valid_legal_categories = [
            "government_pleader", 
            "additional_government_pleader",
            "assistant_government_pleader",
            "b_panel_advocate",
            "advocate_general"
        ]
        self.legal_category_display_names = {
            "government_pleader": "Government Pleader",
            "additional_government_pleader": "Additional Government Pleader", 
            "assistant_government_pleader": "Assistant to Government Pleader",
            "b_panel_advocate": "B Panel Advocate",
            "advocate_general": "Advocate General"
        }
    
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
    
    def create_user_profile(self, uid: str, email: str, role: str = "user", legal_category: str = "assistant_government_pleader", full_name: str = None) -> Dict:
        """
        Create or update user profile in Firestore
        
        Args:
            uid: Firebase UID
            email: User email
            role: One of the valid roles ('admin' or 'user')
            legal_category: Legal professional category
            full_name: User's full name
        """
        try:
            # Validate role
            if role not in self.valid_roles:
                role = "user"  # Default to user role
                
            # Check if this is the initial admin setup
            if email == "deshpande.mak@gmail.com":
                role = "admin"
                legal_category = None  # Admins don't need legal categories
            
            user_data = {
                "uid": uid,
                "email": email,
                "role": role,
                "legal_category": legal_category if role != "admin" else None,
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
                        "full_name": firebase_user.email.split("@")[0] if firebase_user.email else "Unknown",
                        "is_active": True,
                        "needs_setup": True  # Flag to show setup is needed
                    }
                else:
                    return {
                        "uid": uid,
                        "email": firebase_user.email,
                        "role": "user",  # Default to user role
                        "legal_category": "assistant_government_pleader",  # Default legal category
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
    
    def admin_update_user_profile(self, target_uid: str, updates: Dict, admin_uid: str) -> Dict:
        """Admin-only update of user profile including role and AGP assignments"""
        try:
            # Verify admin permissions
            if not self.is_admin(admin_uid):
                raise HTTPException(status_code=403, detail="Admin access required")
            
            # Validate role if provided
            if 'role' in updates:
                role = updates['role']
                if role not in self.valid_roles:
                    raise HTTPException(status_code=400, detail=f"Invalid role: {role}. Must be one of: {', '.join(self.valid_roles)}")
            
            # Allow admin to update role, legal_category, and other user info
            allowed_updates = ['role', 'legal_category', 'full_name', 'is_active']
            filtered_updates = {k: v for k, v in updates.items() if k in allowed_updates}
            filtered_updates['updated_at'] = datetime.now()
            
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
    
    def get_user_agp_filter(self, uid: str) -> Optional[str]:
        """Get the user's full name for data filtering - returns None for admins, full_name for regular users"""
        try:
            profile = self.get_user_profile(uid)
            
            if not profile.get('is_active', True):
                raise HTTPException(status_code=403, detail="Account is disabled. Contact administrator.")
            
            role = profile.get('role')
            
            if role == 'admin':
                return None  # Admins can see all data
            else:
                # Return user's full name for fuzzy matching against AGP data
                full_name = profile.get('full_name', '').strip()
                if not full_name:
                    raise HTTPException(status_code=403, detail="Full name required. Please update your profile.")
                return full_name
                
        except HTTPException:
            raise
        except Exception as e:
            logging.error(f"Error getting user filter: {str(e)}")
            raise HTTPException(status_code=500, detail="Error checking user permissions")
    
    def can_access_agp_data(self, uid: str, agp_name: str) -> bool:
        """Check if user can access data for specific AGP using fuzzy name matching"""
        try:
            user_profile = self.get_user_profile(uid)
            
            # Admins can access all data
            if user_profile.get('role') == 'admin':
                return True
            
            # Regular users can access data if their full_name matches the AGP name (using fuzzy matching)
            full_name = user_profile.get('full_name', '').strip()
            if not full_name:
                return False
            
            # Use fuzzy matching to check if user's name matches the AGP name
            matched_name, confidence = self.match_user_name_to_agp(full_name, [agp_name])
            return confidence >= 0.50  # 50% confidence threshold
            
        except:
            return False
    
    def get_active_user_names(self) -> List[str]:
        """Get list of active user names (for admin user selector in bill generation)"""
        try:
            active_user_names = []
            
            # Get all active users with login credentials
            all_users = self.list_users()
            logging.info(f"📋 get_active_user_names: Found {len(all_users)} total users in collection")
            
            for user in all_users:
                user_name = user.get('full_name', 'NO_NAME')
                user_role = user.get('role', 'NO_ROLE')
                user_active = user.get('is_active', False)
                
                # Skip admin users and inactive users
                if user_role == 'admin':
                    logging.info(f"  ⏭️  Skipping admin: {user_name}")
                    continue
                    
                if not user_active:
                    logging.info(f"  ⏭️  Skipping inactive: {user_name} (role={user_role})")
                    continue
                
                # Get user's full name
                full_name = user.get('full_name', '').strip()
                if full_name:
                    logging.info(f"  ✅ Including: {full_name} (role={user_role})")
                    active_user_names.append(full_name)
                else:
                    logging.info(f"  ⚠️  Skipping user with no name (role={user_role})")
            
            logging.info(f"📤 get_active_user_names returning {len(active_user_names)} users: {sorted(active_user_names)}")
            return sorted(active_user_names)
            
        except Exception as e:
            logging.error(f"Error getting active user names list: {str(e)}")
            import traceback
            logging.error(traceback.format_exc())
            return []
    
    def match_user_name_to_agp(self, user_name: str, agp_names_in_data: List[str]) -> tuple:
        """
        Enhanced fuzzy matching to map user names to AGP names in board/order data
        Handles initials and name permutations (e.g., "Pooja Makarand Joshi Deshpande" → "P.M.J.Deshpande", "P.M.Joshi")
        Returns (best_match, confidence_score)
        """
        from difflib import SequenceMatcher
        import re
        
        if not agp_names_in_data:
            return (None, 0.0)
        
        # Normalize and extract words from user name
        user_name_normalized = user_name.lower().strip()
        user_words = re.findall(r'\b\w+\b', user_name_normalized)
        
        if not user_words:
            return (None, 0.0)
        
        # Generate all possible initial combinations for the user name
        # E.g., "Pooja Makarand Joshi Deshpande" → ["p", "pm", "pmj", "pmjd", "pooja", "deshpande", etc.]
        user_initials = [word[0] for word in user_words]
        user_full_words = user_words.copy()
        
        best_match = None
        best_score = 0.0
        
        for agp_name in agp_names_in_data:
            if not agp_name:
                continue
                
            agp_normalized = agp_name.lower().strip()
            # Remove common titles and punctuation
            agp_normalized = re.sub(r'\b(shri|smt|ms|mr|mrs|dr|adv|advocate|agp|addl|gp)\b', '', agp_normalized)
            agp_normalized = re.sub(r'[.,*#\-/]', ' ', agp_normalized)
            agp_words = [w for w in re.findall(r'\b\w+\b', agp_normalized) if w]
            
            if not agp_words:
                continue
            
            # Calculate multiple similarity metrics
            scores = []
            
            # 1. Last name matching (with fuzzy tolerance for spelling variations and compound names)
            if len(user_words) > 0 and len(agp_words) > 0:
                agp_last = agp_words[-1]
                last_name_score = 0.0
                
                # Check AGP last name against ALL user name words (handles compound last names like "Joshi Deshpande")
                for user_word in user_words:
                    if user_word == agp_last:
                        last_name_score = 1.0
                        break
                    elif user_word in agp_last or agp_last in user_word:
                        last_name_score = max(last_name_score, 0.8)
                    else:
                        # Check for close spelling variations (e.g., Pabale vs Pable)
                        word_similarity = SequenceMatcher(None, user_word, agp_last).ratio()
                        if word_similarity >= 0.75:  # 75% similar
                            last_name_score = max(last_name_score, word_similarity * 0.9)
                
                # If no decent last name match found, skip this AGP
                if last_name_score < 0.60:  # Slightly lenient for spelling variations
                    continue
                
                scores.append(('last_name', last_name_score, 0.35))
            
            # 2. Check if AGP name contains user's initials pattern
            # E.g., "p.m.joshi" matches "Pooja Makarand Joshi"
            agp_initials = []
            for word in agp_words:
                if len(word) == 1 or (len(word) == 2 and word[1] == '.'):
                    agp_initials.append(word[0])
            
            if agp_initials and user_initials:
                # Check if user initials match AGP initials in sequence
                initials_match = 0.0
                if len(agp_initials) <= len(user_initials):
                    # Check if AGP initials are a subset of user initials in order
                    matches = sum(1 for i, agp_init in enumerate(agp_initials) if i < len(user_initials) and agp_init == user_initials[i])
                    if matches > 0:
                        initials_match = matches / len(user_initials)
                scores.append(('initials', initials_match, 0.25))
            
            # 3. Check for full word matches (e.g., "Pooja" in full, not just "P")
            full_word_matches = 0
            for user_word in user_words:
                for agp_word in agp_words:
                    if len(user_word) > 1 and len(agp_word) > 1:  # Both are full words
                        if user_word == agp_word:
                            full_word_matches += 1
                        elif user_word in agp_word or agp_word in user_word:
                            full_word_matches += 0.5
            
            if len(user_words) > 0:
                full_word_score = min(full_word_matches / len(user_words), 1.0)
                scores.append(('full_words', full_word_score, 0.25))
            
            # 4. Overall sequence similarity
            seq_score = SequenceMatcher(None, user_name_normalized, agp_normalized).ratio()
            scores.append(('sequence', seq_score, 0.15))
            
            # Calculate weighted combined score
            combined_score = sum(score * weight for _, score, weight in scores)
            
            if combined_score > best_score:
                best_score = combined_score
                best_match = agp_name
        
        return (best_match, best_score)
    
    def get_available_roles(self) -> Dict[str, str]:
        """Get available user roles with their display names"""
        return self.role_display_names
    
    def is_legal_professional(self, role: str) -> bool:
        """Check if a role is a legal professional role (not admin)"""
        return role == 'user'  # Only users (not admin) are legal professionals
    
    def get_available_legal_categories(self) -> Dict[str, str]:
        """Get available legal categories with their display names"""
        return self.legal_category_display_names
    
    def is_valid_legal_category(self, legal_category: str) -> bool:
        """Check if a legal category is valid"""
        return legal_category in self.valid_legal_categories
    
    def list_firebase_auth_users(self) -> List[Dict]:
        """List all users from Firebase Authentication"""
        try:
            firebase_users = []
            page = auth.list_users()
            
            while page:
                for user in page.users:
                    # Handle Firebase Auth timestamps (Unix timestamps in seconds)
                    created_timestamp = None
                    if user.user_metadata.creation_timestamp:
                        created_timestamp = datetime.fromtimestamp(user.user_metadata.creation_timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')
                    
                    last_signin_timestamp = None
                    if user.user_metadata.last_sign_in_timestamp:
                        last_signin_timestamp = datetime.fromtimestamp(user.user_metadata.last_sign_in_timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')
                    
                    firebase_users.append({
                        'uid': user.uid,
                        'email': user.email,
                        'display_name': user.display_name,
                        'created': created_timestamp,
                        'last_sign_in': last_signin_timestamp,
                        'disabled': user.disabled
                    })
                
                # Get next page if available
                page = page.get_next_page() if page.has_next_page else None
            
            return firebase_users
            
        except Exception as e:
            logging.error(f"Error listing Firebase Auth users: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error listing Firebase Auth users: {str(e)}")
    
    def sync_firebase_users_to_firestore(self, admin_uid: str) -> Dict:
        """Sync Firebase Auth users to Firestore with default AGP role"""
        try:
            # Verify admin permissions
            if not self.is_admin(admin_uid):
                raise HTTPException(status_code=403, detail="Admin access required")
            
            firebase_users = self.list_firebase_auth_users()
            existing_firestore_users = {user['uid']: user for user in self.list_users()}
            
            synced_count = 0
            errors = []
            
            for firebase_user in firebase_users:
                uid = firebase_user['uid']
                email = firebase_user['email']
                
                # Skip if user already exists in Firestore
                if uid in existing_firestore_users:
                    continue
                
                # Skip users without email
                if not email:
                    continue
                
                try:
                    # Determine role - make deshpande.mak@gmail.com admin, others default to user
                    role = 'admin' if email == 'deshpande.mak@gmail.com' else 'user'
                    legal_category = 'assistant_government_pleader' if role != 'admin' else None
                    
                    # Create Firestore profile
                    self.create_user_profile(
                        uid=uid,
                        email=email,
                        role=role,
                        legal_category=legal_category,
                        full_name=firebase_user.get('display_name') or email.split('@')[0]
                    )
                    
                    synced_count += 1
                    logging.info(f"Synced Firebase user {email} to Firestore")
                    
                except Exception as e:
                    error_msg = f"Failed to sync {email}: {str(e)}"
                    errors.append(error_msg)
                    logging.error(error_msg)
            
            return {
                'synced_count': synced_count,
                'total_firebase_users': len(firebase_users),
                'existing_users': len(existing_firestore_users),
                'errors': errors
            }
            
        except Exception as e:
            logging.error(f"Error syncing Firebase users: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error syncing users: {str(e)}")
    
    def get_firebase_auth_users_not_in_firestore(self) -> List[Dict]:
        """Get Firebase Auth users that don't have Firestore profiles"""
        try:
            firebase_users = self.list_firebase_auth_users()
            existing_firestore_users = {user['uid']: user for user in self.list_users()}
            
            unsynced_users = []
            for firebase_user in firebase_users:
                if firebase_user['uid'] not in existing_firestore_users and firebase_user['email']:
                    unsynced_users.append(firebase_user)
            
            return unsynced_users
            
        except Exception as e:
            logging.error(f"Error getting unsynced Firebase users: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error getting unsynced users: {str(e)}")
    

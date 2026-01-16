import pandas as pd
import numpy as np
import re
import math
import random
from ortools.sat.python import cp_model

class KnuScheduler:
    def __init__(self, lectures_df):
        """
        lectures_df: DataFrame containing lecture data fetched from Graph DB.
        Required columns: 'id', 'name', 'credit', 'time', 'lat', 'lon', 'grade'
        """
        # Data validation to ensure required columns exist
        required_cols = ['id', 'name', 'credit', 'time']
        for col in required_cols:
            if col not in lectures_df.columns:
                raise ValueError(f"Input dataframe missing required column: {col}")

        self.df = lectures_df.copy()
        self._preprocess()

    def _preprocess(self):
        # Parse time strings into integer indices
        self.df['time_indices'] = self.df['time'].apply(self._parse_time)
        
        # Ensure coordinates are floats (default to 0.0 if missing)
        if 'lat' in self.df.columns:
            self.df['lat'] = pd.to_numeric(self.df['lat'], errors='coerce').fillna(0.0)
        else:
            self.df['lat'] = 0.0
            
        if 'lon' in self.df.columns:
            self.df['lon'] = pd.to_numeric(self.df['lon'], errors='coerce').fillna(0.0)
        else:
            self.df['lon'] = 0.0

    def _parse_time(self, time_str):
        """
        Converts time strings (e.g., 'Mon 1A,1B') into a list of integer indices.
        Format: Day Index (0-5) * 100 + Period Index (0-27)
        """
        if not time_str or pd.isna(time_str): return []
        
        # Mapping: Mon=0, Tue=1, ... Sat=5
        day_map = {'월': 0, '화': 1, '수': 2, '목': 3, '금': 4, '토': 5}
        indices = []
        
        # Extract days and periods using regex
        tokens = re.findall(r'([월화수목금토])|(\d+[A-B])', str(time_str))
        
        current_day = -1
        # Period mapping: 1A=0, 1B=1, 2A=2, ...
        p_map = {f"{i}{p}": (i-1)*2 + (0 if p=='A' else 1) for i in range(1, 15) for p in ['A', 'B']}
        
        for d, p in tokens:
            if d: 
                current_day = day_map.get(d, -1)
            elif p and current_day != -1 and p in p_map:
                indices.append(current_day * 100 + p_map[p])
                
        return indices

    def _haversine(self, lat1, lon1, lat2, lon2):
        """Calculates distance between two coordinates in meters."""
        R = 6371000 # Earth radius in meters
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        return R * c

    def solve(self, config, num_solutions=3):
        """
        Generates optimal schedules based on constraints.
        
        config parameters:
            - min_credit (int): Minimum total credits
            - max_credit (int): Maximum total credits
            - must_have (list): List of course names that MUST be included
            - preferred (list): List of course names to prioritize (Roadmap recommendations)
            - user_grade (str/int): Student's grade level for prioritization
            - block_times (list of tuples): Time ranges to exclude (e.g., [(400, 500)] for Friday)
            - weights (dict): Custom weights for objective function
        """
        model = cp_model.CpModel()
        candidates = self.df.to_dict('records')
        
        # Create Boolean variables for each course (1 if selected, 0 otherwise)
        vars = {i: model.NewBoolVar(f"c_{i}") for i in range(len(candidates))}
        
        # --- Constraints ---

        # 1. Time Conflict & Physical Distance Constraints
        MAX_DIST = 800 # Max travel distance in meters (10 min break)
        
        for i in range(len(candidates)):
            for j in range(i + 1, len(candidates)):
                ti = sorted(candidates[i]['time_indices'])
                tj = sorted(candidates[j]['time_indices'])
                
                # Skip if either course has no time data
                if not ti or not tj: continue

                # A. Direct Time Overlap
                if not set(ti).isdisjoint(tj):
                    model.Add(vars[i] + vars[j] <= 1)
                    continue
                
                # B. Travel Distance for Consecutive Classes
                dist = 0
                # Only calculate if coordinates are available
                if candidates[i]['lat'] != 0 and candidates[j]['lat'] != 0:
                    dist = self._haversine(candidates[i]['lat'], candidates[i]['lon'],
                                           candidates[j]['lat'], candidates[j]['lon'])
                
                if dist > MAX_DIST:
                    # Check if classes are consecutive (End of one == Start of other)
                    if ti[-1] + 1 == tj[0]: model.Add(vars[i] + vars[j] <= 1)
                    elif tj[-1] + 1 == ti[0]: model.Add(vars[i] + vars[j] <= 1)

        # 2. Duplicate Course Prevention (Same name, different section)
        name_groups = {}
        for i, c in enumerate(candidates):
            if c['name'] not in name_groups: name_groups[c['name']] = []
            name_groups[c['name']].append(vars[i])
            
        for v_list in name_groups.values():
            model.Add(sum(v_list) <= 1)

        # 3. Must-Have Courses (Hard Constraint)
        # Using partial match to handle slight name variations
        for target in config.get('must_have', []):
            relevant = [vars[i] for i, c in enumerate(candidates) if target in c['name']]
            if relevant:
                model.Add(sum(relevant) >= 1)

        # 4. Credit Limits
        total_credits = sum(vars[i] * int(c['credit']) for i, c in enumerate(candidates))
        model.Add(total_credits >= config.get('min_credit', 15))
        model.Add(total_credits <= config.get('max_credit', 21))

        # --- Objective Function (Maximizing Score) ---
        score_terms = []
        weights = config.get('weights', {})
        
        # Default weights
        w_preferred = weights.get('preferred', 300)
        w_grade = weights.get('grade_match', 200)
        w_morning = weights.get('morning_penalty', 50)
        
        for i, c in enumerate(candidates):
            score = 100 # Base score
            
            # A. Preferred Courses (Roadmap / Guide recommendations)
            if any(p in c['name'] for p in config.get('preferred', [])):
                score += w_preferred
                
            # B. Grade Matching
            # Prioritize courses matching the user's current grade
            if str(c.get('grade', '')) == str(config.get('user_grade', '')):
                score += w_grade

            # C. Avoid Blocked Times (e.g., No Friday classes)
            for start, end in config.get('block_times', []):
                if any(start <= t < end for t in c['time_indices']):
                    score -= 1000 # Heavy penalty
            
            # D. Avoid Early Morning Classes (e.g., 9 AM)
            # Checks for indices ending in 0-3 (approx. before 10 AM)
            if any((t % 100) < 4 for t in c['time_indices']):
                 score -= w_morning

            score_terms.append(vars[i] * int(score))

        model.Maximize(sum(score_terms))
        
        # --- Solve ---
        solver = cp_model.CpSolver()
        # Using 0 linearization level for potentially faster solving on this scale
        solver.parameters.linearization_level = 0
        
        solutions = []
        
        # Iterate to find multiple diverse solutions by randomizing seeds
        for _ in range(num_solutions * 3): # Attempt more times to ensure valid solutions
            if len(solutions) >= num_solutions: break
            
            solver.parameters.random_seed = random.randint(0, 99999)
            status = solver.Solve(model)
            
            if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
                selected = [candidates[i] for i in range(len(candidates)) if solver.Value(vars[i])]
                
                # Create a hash of the schedule (sorted IDs) to prevent duplicates
                h = tuple(sorted(s['id'] for s in selected))
                
                if not any(sol['hash'] == h for sol in solutions):
                    solutions.append({
                        'hash': h,
                        'lectures': selected,
                        'total_credit': sum(int(s['credit']) for s in selected)
                    })
        
        return solutions
-- One "Other" section for now: visits filed under Other animals move to Other. Each visit keeps its species.
UPDATE visit SET category = 'other' WHERE category = 'other_animals';
UPDATE undo SET before_json = replace(before_json, '"other_animals"', '"other"');
